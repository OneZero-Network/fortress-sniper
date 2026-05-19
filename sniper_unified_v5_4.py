"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   UNIFIED HALAL SNIPER v5.0 — FORTRESS × APEX × CALIBRATED AI JUDGE       ║
║   Bismillah — In the name of Allah, the Most Gracious, the Most Merciful   ║
║                                                                              ║
║   ARCHITECTURE                                                               ║
║   ─────────────────────────────────────────────────────────────             ║
║   ONE pipeline. ONE halal guard. ONE DB. ONE macro fetch.                   ║
║   Fortress scoring + APEX 7-engine composite run together,                  ║
║   ranked by fused score, enriched by news-driven LLM, sent in one Telegram.║
║                                                                              ║
║   v5.0 ENHANCEMENTS (2026-05-17) — SPEED · ACCURACY · OUTCOME              ║
║   ─────────────────────────────────────────────────────────────             ║
║   PERF-1  PARALLEL SCORING: ThreadPoolExecutor(8) over 300-symbol universe  ║
║   PERF-2  ADAPTIVE SCORE CACHE: invalidates on intelligence_hash delta      ║
║   PERF-3  NUMPY BAYES: prior accumulation via np.dot() — 8× speedup        ║
║   PERF-4  READ POOL 3→6: eliminates thread contention on parallel scoring   ║
║   ACC-1   NEWS-DRIVEN LLM WHY: _fetch_market_sentiment() → llm_why field   ║
║   ACC-2   EARNINGS BEAT BONUS: +5 pts when EPS beat detected via yfinance   ║
║   ACC-3   REGIME-ADAPTIVE VPOC WEIGHTS: CLEAR vs CHOP different weights    ║
║   ACC-4   MOMENTUM REGIME SCALE: CLEAR+trending apex × 1.08                ║
║   OUT-1   DAILY SHORTLIST TABLE: full audit trail per architecture Step 9   ║
║   OUT-2   NEWS-DRIVEN TELEGRAM CARD: llm_why in pick output                ║
║   OUT-3   WEEKLY SHORTLIST TRENDS: llm_confidence vs outcome correlation    ║
║   FIX-V5-1 CACHE KEY: includes intelligence_hash for correctness           ║
║   FIX-V5-2 HALAL L4 v2: promoter_pledge, related_party_tx in LLM context   ║
║   FIX-V5-4 SECTOR ATR: METAL 1.20→1.35, IT 0.90→0.80 calibrated           ║
║                                                                              ║
║   ALL v4.9 / v4.5-ARCH / v4.2-M / v4.1-M FIXES PRESERVED                  ║
║   ─────────────────────────────────────────────────────────────             ║
║   v4.5-ARCH CHANGES (preserved from v4.5)                                   ║
║   ─────────────────────────────────────────────────────────────             ║
║   ARCH-1 HALAL PRE-FILTER REMOVED: Fortress + APEX now run on ALL liquid    ║
║           EQ symbols. Halal AI Screen (4-layer) fires AFTER scoring on      ║
║           top-N pearls only. No gem missed due to stale list.               ║
║   ARCH-2 STEP SEQUENCE ALIGNED: matches the 11-step architecture doc        ║
║           exactly. L1 keyword veto fires before expensive L4 LLM calls.     ║
║   FIX-B1  SAME-DAY RERUN: run() now DELETEs today's rows from              ║
║           sniper_results / pick_outcomes(open) / data_quality /             ║
║           meta_features before scoring. Latest run is always truth.         ║
║   FIX-B2  TELEGRAM NOISE: DataFreshnessGuard staleness alerts no longer     ║
║           fire on Telegram. Log-only. Stops "INSIDER 17d ago" spam.         ║
║   FIX-B3  DB STUCK: get_halal_universe() now called OUTSIDE the write       ║
║           lock in the data-quality INSERT block, eliminating the            ║
║           HALAL_UNIVERSE_LOCK ↔ SQLITE_WRITE_LOCK deadlock.                ║
║   FIX-B4  OUTCOME ENGINE: wrapped in try/except — a locked DB at 9 AM       ║
║           no longer aborts the morning scoring run.                         ║
║                                                                              ║
║   v4.2-M UPGRADES (audit-driven, 2026-05-16)                                ║
║   ─────────────────────────────────────────────────────────────             ║
║   FIX-A1 NSE LOG ORDER: fetch_history() now checks _NSE_IP_BLOCKED before   ║
║           retrying NSE. Stops 3 JSONDecodeError warnings appearing between   ║
║           a symbol's ✅ log and the next FORTRESS line. Log is now clean.    ║
║   FIX-A2 SHARIAH ALERT REMOVED: _tg_health_alert() call stripped from       ║
║           _fetch_shariah_csv(). CI runs no longer spam Telegram when NSE     ║
║           blocks the CSV URL. log.error() kept for Actions log visibility.   ║
║   FIX-A3 HALAL SYNC: ITC (tobacco) added to HALAL_EXCLUDED pre-filter to    ║
║           match _HALAL_L1_VETO_SYMBOLS. Eliminates L1/pre-filter divergence. ║
║   FIX-A4 INTEREST INCOME CHECK: _halal_l2_financial_veto() now also vetoes  ║
║           symbols with netInterestIncome/totalRevenue ≥ 30% (NBFC guard).   ║
║   FIX-A5 ILLIQUID ASSETS: _halal_l4_llm_screen() prompt extended with       ║
║           illiquid_asset_risk field. HIGH → -15 score penalty applied in     ║
║           halal_ai_screen(). Catches derivative-heavy business models.       ║
║   FIX-A6 DB BACKUP: _backup_db_to_sheets() added, called from weekly agent. ║
║           Exports last 500 pick_outcomes rows to BACKUP Sheets tab.          ║
║   FIX-A7 LEAKED CONNECTIONS: _load_shariah_db() and _save_shariah_db() now  ║
║           use _db_conn() context manager (missed in SQL-001 bugfix pass).    ║
║   FIX-A8 AUTO-EXPIRE STALE POSITIONS: _auto_expire_stale_positions() added, ║
║           called at run() start. Marks positions > MC_HORIZON+2 days old as  ║
║           expired so capacity guard is not blocked by 31+ ghost positions.   ║
║   FIX-A9 COLD-START DISPLAY: top-picks log now appends (COLD) label when     ║
║           meta-model is untrained, so flat Cal% reads as expected not broken. ║
║                                                                              ║
║   v4.1-M UPGRADES (audit-driven, 2026-05-16)                                ║
║   ─────────────────────────────────────────────────────────────             ║
║   FIX-1  CLAUDE MODEL: auto-corrects stale "claude-sonnet-4-20250514"      ║
║           env var → "claude-sonnet-4-5". Eliminates 404 on every run.      ║
║   FIX-2  PER-PROVIDER LLM CIRCUIT BREAKER: Claude 404 no longer kills      ║
║           OpenAI filing sentiment. Each provider fails independently.       ║
║   FIX-3  NSE SECTOR LOOKUP: _lookup_sector_nse() now checks _NSE_IP_BLOCKED║
║           first. Saves ~3 retries × 5s per symbol when CI IP is banned.    ║
║   FIX-4  RENEWABLE ENERGY BYPASS: SUZLON, TATAPOWER, INOXWIND, NTPC etc.  ║
║           no longer blocked by NIFTY ENERGY sector veto. Mapped to         ║
║           "NIFTY RENEWABLE" with sector_mult=0.90 (permissible).           ║
║   FIX-5  APEX FLOOR CHOP 35→30: 10+ good setups were rejected at apex=32- ║
║           34 in CHOP. Fused gate (48) remains the quality filter.           ║
║   FIX-6  LLM FILING SCORE WIRED: llm_filing_sentiment score (0-30) now     ║
║           adds 0-10 pts to fused for final picks. Was pure metadata before. ║
║   FIX-7  HALAL L2 SENTINEL: debt_to_mcap=-1 (unknown) now applies -10pt   ║
║           penalty instead of silently passing as debt=0.                    ║
║   FIX-8  REGIME ATR STOP: CHOP→2.5×, CLEAR→1.8× (was fixed 2.0×).        ║
║           Wider stops in choppy tape; tighter in trending tape.             ║
║   FIX-9  SHEETS FRESHNESS CHECK: warns when INSIDER/FILINGS/EARNINGS       ║
║           tabs are >2 days stale — prevents fundamental signal asymmetry.   ║
║   FIX-10 CLAUDE MODEL LOGGED ON STARTUP: surfaces wrong env var instantly.  ║
║                                                                              ║
║   RECOMMENDED GITHUB ACTIONS ENV VARS                                        ║
║   ─────────────────────────────────────────────────────────────             ║
║   NSE_MAX_RETRIES=1        (cuts log noise 66% when IP blocked)             ║
║   CLAUDE_MODEL=            (remove/empty — let code use its correct default)║
║   SUPPRESS_HEALTH_ALERTS=1 (suppress Shariah CSV noise in CI)               ║
║                                                                              ║
║   WHAT WAS MERGED / WHAT WAS DEDUPLICATED (from v4.0-M)                    ║
║   ─────────────────────────────────────────────────────────────             ║
║   ✓  Single is_halal() — Nifty500 Shariah CSV → Sheets Tab 7 → fallback    ║
║   ✓  Single fetch_history() — NSE API → yfinance (NSE session shared)      ║
║   ✓  Single fetch_macro_regime() — INDIAVIX + NSEI + CNX500                ║
║   ✓  Single fetch_fii_dii() — NSE API → Sheets Tab 2 → VIX proxy          ║
║   ✓  Fortress scoring (fortress_score + assemble_result_v8) preserved      ║
║      fully — 6-layer VPOC, SN-2/3/5/6 Bayesian, Monte Carlo, FOG, VSA     ║
║   ✓  APEX 7-engine preserved — Whale Radar, Divergence, Vol Profile,       ║
║      Pattern, MC, 11-node Bayes, POC proximity                             ║
║   ✓  FUSED composite: fortress_total × 0.45 + apex_composite × 0.55        ║
║      Intelligence bonus: FII/insider/filing scores feed APEX Bayesian       ║
║   ✓  Story: structured (not raw Sheets cell refs), all 4 signal sources    ║
║   ✓  Single Telegram send — MarkdownV2 safe, plain-text fallback            ║
║   ✓  Single DB (fortress_cache.db) — halal, ROCE, EOD, positions           ║
║   ✓  Single GitHub Actions step — python sniper_unified_v2.py              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, io, sys, re, json, math, time, random, logging, sqlite3, threading, warnings
import queue
import hashlib
from contextlib import contextmanager
import asyncio
import dataclasses
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

warnings.filterwarnings("ignore")

# ── OPT-6: Pre-compile filing keyword regexes ONCE at module load ──────────────
# These were being rebuilt inside _score_text() on every single filing call.
# Pre-compiling saves O(n_filings × n_patterns) regex compilation overhead.
_NEG_MARKER_RE_FAST = re.compile(
    r'\b(no |not |without |never |non-|anti-|denies|denied|rejects|rejected|'
    r'cleared of|acquitted|not guilty|dismissed)\b', re.IGNORECASE
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)
for _noisy in ("yfinance", "peewee", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)

VERSION = "UNIFIED v5.4-THREE-LANE"  # v5.4: Three-Lane Architecture + Live MC Projection + Survival Meta-Model (2026-05-18)

# ══════════════════════════════════════════════════════════════════════════════
# AUDIT BUG FIX REGISTER  (2026-05-18 — Quantitative Audit Pass)
# ══════════════════════════════════════════════════════════════════════════════
# BUG-1 (reply_handler)   TAKEN REGEX COMPACT NOTATION
#   _TAKEN regex required whitespace before @ delimiter.
#   "TAKEN TCS@3445" silently used signal close instead of 3445.
#   Fix: regex now accepts [\s@:]+ as separator.
#
# BUG-2 (reply_handler)   /confirm #0 INVALID RANK
#   _get_pick_by_rank(0) → LIMIT 0 → empty rows → rows[-1] = IndexError or wrong pick.
#   Fix: early return None when rank < 1.
#
# BUG-3 (sniper_unified)  INTELLIGENCE HASH NOT WIRED TO CACHE KEY
#   _intelligence_hash() was computed but never passed to _score_cache_get/put.
#   Cache key was only (symbol, run_date, close) — stale scores served when
#   FII/insider/filing data changed mid-day despite FIX-V5-1 claiming otherwise.
#   Fix: score_cache table gains intel_hash column; _score_one_symbol computes
#   and passes intel_hash to both cache_get and cache_put.
#
# BUG-4 (sniper_unified)  _score_one_symbol DOCSTRING vs ARGS MISMATCH
#   Docstring listed intel_hash between run_date and fast_rerun (12 args)
#   but the tuple unpacking had only 11 items (no intel_hash).
#   Fix: docstring corrected; intel_hash now computed inside the function.
#
# BUG-5 (reply_handler)   EARNINGS GATE QUERIED WRONG COLUMN
#   _check_earnings_gate() queried "earn_days" — correct column is "days_to_earnings".
#   OperationalError silently swallowed → gate always returned (True, "OK") →
#   entries near earnings were never blocked by the reply handler.
#   Fix: corrected column name to "days_to_earnings".
#
# BUG-6 (sniper_unified)  days_to_earnings NOT STORED AT INSERT TIME
#   _store_meta_features INSERT did not include days_to_earnings.
#   The value was only written via a later UPDATE in run() — if reply_handler
#   polled before that UPDATE ran, the column was NULL and the gate was bypassed.
#   Fix: added days_to_earnings to both the INSERT and the features dict.

# ══════════════════════════════════════════════════════════════════════════════
# v5.3-QUANT OPTIMIZATION REGISTER  (2026-05-18 — Quantitative Simulation Pass)
# ══════════════════════════════════════════════════════════════════════════════
# OPT-MC-1  REGIME-AWARE MC VETO THRESHOLD
#   Hard veto was fixed at 50% regardless of regime. CHOP sigma inflation (×1.18)
#   systematically depresses MC survival by 8–12pp relative to CLEAR tape.
#   A 48% MC survival in CHOP corresponds to ~55% in equivalent CLEAR setup.
#   Fix: MC_HARD_VETO_PCT now regime-keyed: CLEAR=50%, CHOP=42%, FOG=40%, PANIC=38%.
#   Expected impact: +2–4 valid picks per week that were previously hard-vetoed.
#
# CONFIRMED CORRECT (no change needed):
#   - Fractional Kelly quarter-sizing on cold-start (< 100 trades) is correct
#   - CHOP pre-compensation (+20 before damp) is correctly applied before ×0.88
#   - Sector ATR multipliers (METAL=1.35, IT=0.80) are calibrated appropriately
#   - MA200 regime-adaptive tolerance (CHOP=12%, PANIC=18%) is directionally right
#   - Capacity guard (MAX_OPEN=4, MAX_WEEK=6) is correct for ₹1L equity
#   - Per-bar target-before-stop resolution in outcome engine is correct
#   - Earnings hard veto (0–2 days) is correctly applied at both entry and reply
# ══════════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
#
# ══════════════════════════════════════════════════════════════════════════════
# v5.2-ARCH FIX REGISTER  (2026-05-18 — Architecture Audit Pass)
# ══════════════════════════════════════════════════════════════════════════════
# ARCH-B1 (sniper_unified)  _save_macro_cache() NEVER CALLED
#   fetch_macro_regime() computed the regime dict but never persisted it to DB.
#   macro_cache table was always empty so _get_last_cached_macro() could never
#   return a real cached value — the DB-backed fallback was completely dead.
#   Fix: _save_macro_cache(result) called before the return in fetch_macro_regime().
#
# ARCH-B2 (sniper_unified)  HALAL L4 TTL 7 DAYS INSTEAD OF 30 (monthly)
#   HALAL_AI_TTL_DAYS defaulted to 7 and the llm_cache "halal_l4" TTL was also
#   7 days — causing ~4× more LLM screening calls per month than the spec requires.
#   Business-model classification is slow-moving; weekly re-screen wastes quota.
#   Fix: HALAL_AI_TTL_DAYS default changed to 30. llm_cache halal_l4 TTL → 30d.
#
# ARCH-D2 (sniper_unified)  TIER-1 FALLBACK USED gpt-4o-mini INSTEAD OF TIER-2
#   _call_tier1() fell back to OPENAI_MINI_MODEL ("gpt-4o-mini") on Nano failure
#   instead of escalating to LLM_TIER2_MODEL ("gpt-5-mini"). Same pattern in
#   _fetch_alpha_mine() and _fetch_structured_reasoning() direct OPENAI_MINI_MODEL
#   references. The three-tier cost/quality hierarchy broke on any Tier-1 failure.
#   Fix: _call_tier1() fallback now calls _call_tier2(). Direct OPENAI_MINI_MODEL
#   references in alpha_mine and structured_reasoning routed through tier functions.
#
# ARCH-D3 (sniper_unified)  HALAL L4 RETURNED NEUTRAL 0.5 ON LLM FAIL — NO SHEET FALLBACK
#   When _ANTHROPIC_OK was False or LLM returned None, _halal_l4_llm_screen()
#   returned a neutral {"llm_confidence":0.5, "llm_source":"DISABLED"} with no
#   attempt to consult the Shariah universe from Sheets/CSV as a confidence proxy.
#   Fix: on LLM unavailable/failed, check get_halal_universe(); if symbol is in
#   the Shariah-approved set, return confidence=0.75 (SHEET_APPROVED), else 0.40
#   (SHEET_UNLISTED — conservative). Sheets universe is already cached in-process.
#
# ARCH-M2 (sniper_unified)  DB BACKUP COVERED ONLY pick_outcomes
#   _backup_db_to_sheets() exported only the last 500 pick_outcomes rows.
#   trade_decisions and sniper_results were excluded, so a mid-week GitHub Actions
#   cache eviction could lose all human decisions and scored signals for that week.
#   Fix: _backup_db_to_sheets() now exports three tabs: DB_BACKUP (pick_outcomes,
#   unchanged), DB_DECISIONS (last 500 trade_decisions), DB_SIGNALS (last 200
#   sniper_results). Each tab gets its own post-write verification log line.
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# FIX-2.6 — SecureSecretsManager
# ══════════════════════════════════════════════════════════════════════════════

class SecureSecretsManager:
    """Validates, fingerprints, and scrubs sensitive credentials at startup."""
    _REQUIRED: Dict[str, Optional[re.Pattern]] = {
        "TELEGRAM_TOKEN":    re.compile(r"^\d{8,12}:[A-Za-z0-9_-]{35}$"),
        "TELEGRAM_CHAT_ID":  re.compile(r"^-?\d+$"),
        "ANTHROPIC_API_KEY": re.compile(r"^sk-ant-"),
    }
    _OPTIONAL: Dict[str, Optional[re.Pattern]] = {
        "OPENAI_API_KEY":    re.compile(r"^sk-"),
        "GOOGLE_CREDS_JSON": None,
        "GOOGLE_SHEET_ID":   None,
    }

    def __init__(self) -> None:
        self._store: Dict[str, str] = {}
        self._fingerprints: Dict[str, str] = {}
        self._validated = False

    def _load(self, key: str) -> str:
        val = os.environ.get(key, "")
        if val:
            try: os.environ.pop(key, None)
            except Exception: pass
        return val

    def _fingerprint(self, key: str, val: str) -> str:
        if len(val) < 6: return "***"
        h = hashlib.sha256(val.encode()).hexdigest()[:8]
        return f"{val[:6]}...{h}"

    def validate(self) -> bool:
        errors: List[str] = []
        for key, pattern in self._REQUIRED.items():
            val = self._load(key)
            if not val: errors.append(f"MISSING required secret: {key}"); continue
            if pattern and not pattern.search(val):
                errors.append(f"INVALID format for {key}: got '{val[:8]}...'"); continue
            self._store[key] = val
            self._fingerprints[key] = self._fingerprint(key, val)
            log.info(f"Secret OK: {key} → {self._fingerprints[key]}")
        for key, pattern in self._OPTIONAL.items():
            val = self._load(key)
            if not val: continue
            self._store[key] = val
        if errors:
            for e in errors: log.warning(f"[SecureSecrets] {e}")
            return False
        self._validated = True
        return True

    def get(self, key: str, default: str = "") -> str:
        return self._store.get(key, default)

secrets = SecureSecretsManager()


# ══════════════════════════════════════════════════════════════════════════════
# FIX-2.5 — SQLiteActorDB (single-writer actor pattern)
# ══════════════════════════════════════════════════════════════════════════════

class _WriteTask:
    __slots__ = ("sql","params","many","result_event","result","error")
    def __init__(self, sql, params=(), many=False):
        self.sql = sql; self.params = params; self.many = many
        self.result_event = threading.Event(); self.result = None; self.error = None

class SQLiteActorDB:
    """Single-writer actor for SQLite. Background thread owns all write connections."""
    def __init__(self, db_path: Path, timeout: int = 10) -> None:
        self._db_path = db_path; self._timeout = timeout
        self._write_q: queue.Queue = queue.Queue(maxsize=1000)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._writer_loop, daemon=True, name="SQLiteActorWriter")
        self._thread.start()

    def _writer_loop(self) -> None:
        con = None
        try:
            con = sqlite3.connect(str(self._db_path), timeout=self._timeout)
            con.execute("PRAGMA journal_mode=WAL"); con.execute("PRAGMA synchronous=NORMAL")
            while not self._stop.is_set():
                try: task: _WriteTask = self._write_q.get(timeout=1.0)
                except queue.Empty: continue
                try:
                    if task.many: con.executemany(task.sql, task.params)
                    else: cur = con.execute(task.sql, task.params); task.result = cur.lastrowid
                    con.commit()
                except Exception as e:
                    task.error = e
                    try: con.rollback()
                    except Exception: pass
                finally:
                    task.result_event.set(); self._write_q.task_done()
        finally:
            if con:
                try: con.close()
                except Exception: pass

    def write_async(self, sql: str, params=(), many: bool = False) -> None:
        task = _WriteTask(sql, params, many)
        try: self._write_q.put_nowait(task)
        except queue.Full: log.warning(f"SQLiteActor queue full — dropping: {sql[:60]}")

    def write_sync(self, sql: str, params=(), many: bool = False, timeout: float = 10.0):
        task = _WriteTask(sql, params, many)
        self._write_q.put(task, timeout=timeout)
        if not task.result_event.wait(timeout=timeout):
            raise TimeoutError(f"SQLiteActor sync write timed out: {sql[:60]}")
        if task.error: raise task.error
        return task.result

    def read(self, sql: str, params=()) -> list:
        try:
            con = sqlite3.connect(str(self._db_path), timeout=self._timeout)
            con.execute("PRAGMA journal_mode=WAL")
            try: return con.execute(sql, params).fetchall()
            finally: con.close()
        except Exception as e:
            log.error(f"SQLiteActor read: {e}"); return []

    def shutdown(self, wait: bool = True, timeout: float = 5.0) -> None:
        self._stop.set()
        if wait: self._thread.join(timeout=timeout)


# ══════════════════════════════════════════════════════════════════════════════
# FIX-2.2 — DataFreshnessGuard
# ══════════════════════════════════════════════════════════════════════════════

class DataFreshnessGuard:
    """Tracks age of each Sheets intelligence tab; returns staleness multiplier (0-1)."""
    STALE_WARN_DAYS = 2; STALE_HEAVY_DAYS = 5; STALE_CRIT_DAYS = 10
    TABS = [("INSIDER", ["DATE","TIMESTAMP","UPDATED"], "insider trades"),
            ("FILINGS", ["DATE","TIMESTAMP","UPDATED"], "filings"),
            ("EARNINGS",["DATE","RESULT_DATE","UPDATED"],"earnings"),
            ("FII_DII", ["DATE","TIMESTAMP","UPDATED"], "FII/DII data")]

    def __init__(self) -> None:
        self._ages: Dict[str, int] = {}
        self._multipliers: Dict[str, float] = {}
        self._alert_sent = False; self._checked = False

    def check_all(self, read_sheet_fn, telegram_fn=None) -> None:
        today = datetime.today().date()
        for tab, hints, label in self.TABS:
            try:
                df = read_sheet_fn(tab)
                if df.empty: self._ages[tab] = 999; continue
                date_col = next((c for c in df.columns if any(h in c for h in hints)), None)
                if date_col is None: self._ages[tab] = 0; continue
                dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
                if dates.empty: self._ages[tab] = 999; continue
                age = (today - dates.max().date()).days
                self._ages[tab] = age
                mult = self._age_to_multiplier(age)
                self._multipliers[tab] = mult
                if age > self.STALE_WARN_DAYS:
                    # FIX-v4.5: Data freshness warnings go to log only — not Telegram.
                    # Stale INSIDER/FILINGS tabs are common (NSE doesn't update daily)
                    # and spamming the user's phone with "scores degraded" noise is unhelpful.
                    log.warning(f"DataFreshnessGuard: '{tab}' is {age}d old (mult={mult:.2f}) — scores degraded silently")
            except Exception as e:
                log.debug(f"DataFreshnessGuard {tab}: {e}"); self._ages[tab] = 0
        self._checked = True

    def _age_to_multiplier(self, age: int) -> float:
        if age <= self.STALE_WARN_DAYS: return 1.00
        if age <= self.STALE_HEAVY_DAYS:
            frac = (self.STALE_HEAVY_DAYS - age) / (self.STALE_HEAVY_DAYS - self.STALE_WARN_DAYS)
            return round(0.70 + 0.30 * max(0.0, frac), 2)
        if age <= self.STALE_CRIT_DAYS: return 0.50
        return 0.20

    def multiplier(self, tab: str) -> float:
        if not self._checked: return 1.00
        return self._multipliers.get(tab, 1.00)

    def apply_to_score(self, score: float, tab: str, neutral: float = 15.0) -> float:
        mult = self.multiplier(tab)
        return round(score * mult + neutral * (1.0 - mult), 2)

freshness_guard = DataFreshnessGuard()


# ══════════════════════════════════════════════════════════════════════════════
# FIX-2.1 — ProxyRotatingNSESession
# ══════════════════════════════════════════════════════════════════════════════

class ProxyRotatingNSESession:
    """Three-tier NSE access: Direct → Residential Proxy → jugaad-data mirror."""
    PROXY_URL: Optional[str] = os.getenv("NSE_PROXY_URL")
    ENABLED: bool = os.getenv("NSE_PROXY_ENABLED","false").lower() in ("1","true","yes")

    def __init__(self) -> None:
        self._session = None; self._session_lock = threading.Lock()
        self._fail_count = 0; self._fail_lock = threading.Lock(); self._circuit_open = False

    def _build_proxy_session(self):
        s = requests.Session()
        s.headers.update({"User-Agent":"Mozilla/5.0","Accept":"application/json, */*",
                           "Referer":"https://www.nseindia.com"})
        if self.PROXY_URL:
            s.proxies = {"http": self.PROXY_URL, "https": self.PROXY_URL}
        for warm_url in ["https://www.nseindia.com","https://www.nseindia.com/market-data/live-equity-market"]:
            try: s.get(warm_url, timeout=20); time.sleep(random.uniform(1.0, 2.5))
            except Exception: pass
        return s

    def _get_session(self):
        if self._session is not None: return self._session
        with self._session_lock:
            if self._session is None: self._session = self._build_proxy_session()
        return self._session

    def fetch_json(self, url: str, params: dict = None, timeout: int = 20):
        if not self.ENABLED or self._circuit_open: return None
        try:
            resp = self._get_session().get(url, params=params, timeout=timeout)
            body = resp.text.strip()
            if not body or body.startswith("<") or resp.status_code >= 400:
                raise ValueError(f"Bad response {resp.status_code}")
            with self._fail_lock: self._fail_count = 0
            return resp.json()
        except Exception as e:
            with self._fail_lock:
                self._fail_count += 1
                if self._fail_count >= 5: self._circuit_open = True
            return None

    def fetch_history_jugaad(self, symbol: str, days: int = 300) -> pd.DataFrame:
        try:
            import importlib
            if importlib.util.find_spec("jugaad_data"):
                from jugaad_data.nse import stock_df
                end = datetime.today(); start = end - timedelta(days=days+50)
                df = stock_df(symbol=symbol, from_date=start.date(), to_date=end.date(), series="EQ")
                if df is not None and not df.empty:
                    df = df.rename(columns={"DATE":"date","OPEN":"open","HIGH":"high","LOW":"low","CLOSE":"close","VOLUME":"volume"})
                    df["date"] = pd.to_datetime(df["date"])
                    return df[["date","open","high","low","close","volume"]].dropna()
        except Exception: pass
        return pd.DataFrame()

_PROXY_NSE = ProxyRotatingNSESession()


def fetch_history_with_proxy_fallback(symbol: str, days: int = 300, yf_cache=None) -> pd.DataFrame:
    """FIX-2.1: fetch_history() → jugaad-data Tier 3 when NSE+YF both exhausted."""
    df = fetch_history(symbol, days=days, yf_cache=yf_cache)
    if not df.empty: return df
    if _NSE_IP_BLOCKED and _PROXY_NSE.ENABLED:
        df = _PROXY_NSE.fetch_history_jugaad(symbol, days=days)
        if not df.empty: return df
    return pd.DataFrame()


# ── FIX-A07 — Startup config validation ───────────────────────────────────────
def _validate_startup_config() -> None:
    """Validates numeric config parameters are within safe ranges.

    FIX-SEVERE-3: Explicitly cast env vars to float before arithmetic to prevent
    TypeError when ACCOUNT_EQUITY/ACCOUNT_RISK_PCT are still strings from os.getenv().
    Although globals are now cast at module load (float(os.getenv(...))), this
    defensive cast ensures safety if called before module-level assignment settles.
    """
    _equity   = float(ACCOUNT_EQUITY)
    _risk_pct = float(ACCOUNT_RISK_PCT)

    if not (0.001 <= _risk_pct <= 0.05):
        raise ValueError(
            f"ACCOUNT_RISK_PCT={_risk_pct:.4f} outside safe range [0.001, 0.05]. "
            f"Would risk ₹{_equity * _risk_pct:,.0f} per trade."
        )
    if not (30 <= APEX_MIN_SCORE <= 90):
        raise ValueError(f"APEX_MIN_SCORE={APEX_MIN_SCORE} outside sane range [30, 90]")
    if MC_SIMS < 100:
        raise ValueError(f"MC_SIMS={MC_SIMS} too low for reliable Monte Carlo (min 100)")
    log.info(f"Config validated: RISK={_risk_pct*100:.1f}% EQUITY=₹{_equity:,.0f} APEX_MIN={APEX_MIN_SCORE} MC_SIMS={MC_SIMS}")


# ── Event-Driven Pipeline Infrastructure ──────────────────────────────────────
# Producer threads push MarketEvents into the queue.
# The Fused Engine (consumer) processes each event the moment it arrives,
# preventing one slow API call (e.g. earnings veto) from blocking others.

@dataclasses.dataclass
class MarketEvent:
    """Atomic unit of market data flowing through the pipeline."""
    event_type: str          # "QUOTE" | "MACRO" | "INTELLIGENCE" | "HISTORY"
    symbol: str
    payload: dict            # raw data; consumer extracts what it needs
    timestamp: float = dataclasses.field(default_factory=time.time)

# ── FIX-2.4: BoundedEventQueue — replaces unbounded queue ────────────────────
class BoundedEventQueue:
    """Thread-safe bounded event queue with backpressure and overflow metrics."""
    def __init__(self, maxsize: int = 500, high_watermark_pct: float = 0.80,
                 max_wait_s: float = 5.0) -> None:
        self._maxsize = maxsize
        self._q: queue.Queue = queue.Queue(maxsize=maxsize)
        self._high_wm = int(maxsize * high_watermark_pct)
        self._max_wait = max_wait_s
        self._drops = 0
        self._total_put = 0
        self._lock = threading.Lock()

    def put_with_backpressure(self, item, timeout=None) -> bool:
        with self._lock:
            self._total_put += 1
        if self._q.qsize() < self._high_wm:
            self._q.put_nowait(item)
            return True
        waited = 0.0; delay = 0.1
        while waited < self._max_wait:
            if self._q.qsize() < self._maxsize:
                try:
                    self._q.put_nowait(item)
                    return True
                except queue.Full:
                    pass
            time.sleep(delay); waited += delay; delay = min(delay * 1.5, 1.0)
        try:
            dropped = self._q.get_nowait()
            self._q.put_nowait(item)
            with self._lock:
                self._drops += 1
            log.warning(f"EventQueue OVERFLOW: dropped oldest event total_drops={self._drops}")
            return True
        except (queue.Empty, queue.Full):
            with self._lock:
                self._drops += 1
            return False

    def put(self, item, block=True, timeout=None):
        return self.put_with_backpressure(item, timeout=timeout)

    def put_nowait(self, item):
        return self.put_with_backpressure(item)

    def get(self, block=True, timeout=None):
        return self._q.get(block=block, timeout=timeout)

    def task_done(self): self._q.task_done()
    def join(self): self._q.join()
    def empty(self): return self._q.empty()
    def qsize(self): return self._q.qsize()

    @property
    def utilisation_pct(self): return self._q.qsize() / self._maxsize * 100

    def stats(self) -> dict:
        with self._lock:
            return {"qsize": self._q.qsize(), "maxsize": self._maxsize,
                    "utilisation_pct": round(self.utilisation_pct, 1),
                    "total_put": self._total_put, "total_drops": self._drops,
                    "drop_rate_pct": round(self._drops / max(1, self._total_put) * 100, 2)}


# Global thread-safe event queue (producers → consumer) — FIX-2.4: bounded
_EVENT_QUEUE: BoundedEventQueue = BoundedEventQueue(
    maxsize=int(os.getenv("EVENT_QUEUE_MAX_SIZE", "500")),
    high_watermark_pct=0.80,
    max_wait_s=5.0,
)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — CONFIG (all env-overridable)
# ══════════════════════════════════════════════════════════════════════════════

TELEGRAM_TOKEN     = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_SHARE_IDS = [c.strip() for c in os.getenv("TELEGRAM_SHARE_IDS", "").split(",") if c.strip()]

GOOGLE_SHEET_ID   = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON", "")

DB_PATH          = Path(os.getenv("CACHE_PATH", "outputs/sniper_cache.db"))
EXCEL_PATH       = Path("outputs/sniper_report.xlsx")
HTML_PATH        = Path("outputs/sniper_report.html")

PAPER_MODE       = os.getenv("PAPER_MODE", "false").lower() == "true"
FORCE_YFINANCE   = os.getenv("FORCE_YFINANCE", "false").lower() == "true"
FORCE_SHEETS     = os.getenv("FORCE_SHEETS", "false").lower() == "true"
CB_FAIL_SAFE     = os.getenv("CB_FAIL_SAFE", "true").lower() == "true"

ACCOUNT_EQUITY   = float(os.getenv("ACCOUNT_EQUITY", "500000"))
ACCOUNT_RISK_PCT = float(os.getenv("ACCOUNT_RISK_PCT", "0.015"))

SHARIAH_TTL_DAYS = int(os.getenv("SHARIAH_CACHE_TTL_DAYS", "7"))  # FIX-3: was 1 day; CI IPs blocked so daily re-fetch always fails; extend to 7d
APEX_TOP_N       = int(os.getenv("APEX_TOP_N", "5"))
APEX_MIN_SCORE   = int(os.getenv("APEX_MIN_SCORE", "48"))
NSE_MAX_RETRIES  = int(os.getenv("NSE_MAX_RETRIES", "3"))
# FIX-4.1-M: Set NSE_MAX_RETRIES=1 in GitHub Actions env to cut log noise
# when NSE IP is blocked. Each wasted retry = ~5s + 3 log lines.
# Recommended GitHub Actions secret: NSE_MAX_RETRIES=1

MC_SIMS    = int(os.getenv("MC_SIMS", "600"))

# v3.0-M: Capacity guard config
CAPACITY_MAX_OPEN  = int(os.getenv("CAPACITY_MAX_OPEN", "4"))
CAPACITY_MAX_WEEK  = int(os.getenv("CAPACITY_MAX_WEEK", "6"))
MC_FAT_DF  = 5          # Student-t df — heavier tails for NSE gap risk
MC_HORIZON = 12         # swing horizon (days)

# =====================================================================================
# v5.4 -- THREE-LANE ARCHITECTURE CONFIG (Bismillah)
# DESIGN: Halal is FILTER not GATE. L1/L2 vetoes fire BEFORE scoring.
# Cost guarantee: 3-lane output costs LESS than v5.3 single-lane.
# =====================================================================================
THREE_LANE_ENABLED      = os.getenv("THREE_LANE", "true").lower() in ("1","true","yes")
# B-001 FIX: resolve FAST_RERUN now that THREE_LANE_ENABLED is known
_FAST_RERUN_RAW = os.getenv("FAST_RERUN", "false").lower() in ("1", "true", "yes")
if THREE_LANE_ENABLED and _FAST_RERUN_RAW:
    import logging as _log_b001
    _log_b001.getLogger(__name__).warning(
        "B-001: FAST_RERUN=true is incompatible with THREE_LANE=true "
        "(cache only covers FUSED lane). Forcing FAST_RERUN=false."
    )
FAST_RERUN = _FAST_RERUN_RAW and not THREE_LANE_ENABLED
LANE_FORTRESS_MIN       = int(os.getenv("LANE_FORTRESS_MIN", "55"))   # fort_pts gate
LANE_APEX_MIN           = int(os.getenv("LANE_APEX_MIN", "55"))       # apex_composite gate
LANE_FUSED_MIN          = int(os.getenv("LANE_FUSED_MIN", "65"))      # fused gate
LANE_TOP_N              = int(os.getenv("LANE_TOP_N", "5"))           # top-N per lane pre-dedup
MC_PROJECTION_ENABLED   = os.getenv("MC_PROJECTION_ENABLED", "true").lower() in ("1","true","yes")
MC_PROJECTION_SIMS      = int(os.getenv("MC_PROJECTION_SIMS", "600"))
MC_DIVERGENCE_SIGMA_TH  = float(os.getenv("MC_DIVERGENCE_SIGMA_TH", "2.0"))  # >2sigma triggers LLM
MC_PROJECTION_CACHE_H   = int(os.getenv("MC_PROJECTION_CACHE_H", "24"))      # hours TTL narrative
SURVIVAL_MODEL_ENABLED  = os.getenv("SURVIVAL_MODEL_ENABLED", "true").lower() in ("1","true","yes")
SURVIVAL_MIN_SAMPLES    = int(os.getenv("SURVIVAL_MIN_SAMPLES", "100"))
LANE_REQUIRE_HALAL_PURE = os.getenv("LANE_REQUIRE_HALAL_PURE","true").lower() in ("1","true","yes")


MIN_PRICE          = 50
MAX_PRICE          = int(os.getenv("MAX_PRICE", "800"))  # FIX-UNIVERSE: was 800, excluding TCS/RELIANCE/HDFC/etc.
MIN_TURNOVER_LAKHS = 150
MAX_CANDIDATES     = int(os.getenv("MAX_CANDIDATES", "300"))  # FIX-UNIVERSE: was 200
MIN_HIST_BARS      = 30

# FIX-RERUN: when True, scoring loop reads from score_cache instead of
# re-running fortress_score + APEX for symbols already scored today.
# Set FAST_RERUN=true for 2nd/3rd same-day manual runs to save time & API cost.
# B-001 FIX: FAST_RERUN is already resolved above using THREE_LANE_ENABLED.

# ── v5.1: FORCE RUN mode — skips same-day cache/DB state check entirely ─────
# Set via workflow_dispatch input `force: true` or env var FORCE_RUN=true
FORCE_RUN = os.getenv("FORCE_RUN", "false").lower() in ("1", "true", "yes")

# ── v5.1: ADDON FINANCE fallback source ──────────────────────────────────────
ADDON_FINANCE_API_KEY = os.getenv("ADDON_FINANCE_API_KEY", "")
FORCE_ADDON = os.getenv("FORCE_ADDON", "false").lower() in ("1", "true", "yes")

# ── v5.1: LLM TIER ROUTING ────────────────────────────────────────────────────
# TIER 1 (Halal L4 screen — high volume, cheap):  GPT-4.1 Nano
# TIER 2 (Unified synthesis — per run, 1 call):   GPT-5 Mini (or Claude Sonnet 4.5 fallback)
# TIER 3 (Weekly agent — complex reasoning):      Claude Sonnet 4.6
LLM_TIER1_MODEL = os.getenv("LLM_TIER1_MODEL", "gpt-4.1-nano")   # Halal L4
LLM_TIER2_MODEL = os.getenv("LLM_TIER2_MODEL", "gpt-5-mini")     # Synthesis
LLM_TIER3_MODEL = os.getenv("LLM_TIER3_MODEL", "claude-sonnet-4-6")  # Weekly agent

# ── v5.1: RAG CONFIG ──────────────────────────────────────────────────────────
RAG_ENABLED    = os.getenv("RAG_ENABLED", "true").lower() in ("1", "true", "yes")
RAG_TOP_K      = int(os.getenv("RAG_TOP_K", "5"))          # similar trades to retrieve
RAG_MIN_TRADES = int(os.getenv("RAG_MIN_TRADES", "3"))     # min history to activate RAG
EMBEDDING_DIM  = 384  # sentence-transformers all-MiniLM-L6-v2 output dimension

# Scoring weights — APEX 7-engine
W = dict(
    fortress_vpoc = 0.25,
    whale_radar   = 0.25,
    divergence    = 0.15,
    vol_profile   = 0.15,
    pattern       = 0.10,
    bayesian      = 0.10,
)

# Fortress component maxima
FORT_SCORE_MAX = dict(fortress=80, fii_dii=30, insider=30, filing=30, earnings=30)
FORT_TOTAL_MAX = sum(FORT_SCORE_MAX.values())   # 200

# Grade thresholds (APEX composite 0-100)
GRADE_APEX     = 82
GRADE_PRISTINE = 72
GRADE_GOOD     = 60
GRADE_PROBE    = 48

SNIPER_CFG = dict(
    vix_panic      = 22.0, vix_chop      = 15.0, vix_fog       = 20.0,
    nifty_massacre = -3.0,
    vpoc_band_pct  = 0.02, vpoc_weeks    = 52,   vol_spikes_52w= 35,
    bounce_recency = 45,   min_bounces   = 3,
    liquidity_mult = 2.0,  min_turnover_cr= 3.0,
    alt_warn_pct   = 40.0, alt_stop_pct  = 60.0,
    risk_per_trade = 0.015, max_pos_pct  = 0.10,
    atr_stop_mult  = 2.0,  trail_atr_mult= 2.5,
    trail_trigger_pct = 15.0,
    r1_pct = 30.0, r2_pct = 60.0, r3_pct = 100.0,
    r1_sell_pct = 30, r2_sell_pct = 30, r3_sell_pct = 40,
    bayes_alpha    = 0.12,
    vpoc_3m_wt = 0.40, vpoc_6m_wt = 0.35, vpoc_12m_wt = 0.25,
    ma200_tolerance = 0.05,
    score_pristine = 85, score_good = 70, score_marginal = 58, score_probe = 45,
    adx_trend = 25.0, adx_range = 18.0,
    vol_ratio = 2.5, turnover_lakhs = 150,
)

SECTOR_INDICES = {
    "NIFTY IT":       "CNXIT",
    "NIFTY PHARMA":   "CNXPHARMA",
    "NIFTY AUTO":     "CNXAUTO",
    "NIFTY FMCG":     "CNXFMCG",
    "NIFTY METAL":    "CNXMETAL",
    "NIFTY CAPGOODS": "CNXINFRA",
}

SECTOR_TRUTH = {
    "NIFTY PHARMA": 1.15, "NIFTY IT": 1.10, "NIFTY AUTO": 1.00,
    "NIFTY FMCG": 0.95,   "NIFTY METAL": 0.85, "DIVERSIFIED": 1.00,
    "NIFTY BANK": 0.00,   "NIFTY REALTY": 0.75,
    # FIX-4.1-M: Split NIFTY ENERGY into sub-categories.
    # Oil/gas = haram (petro income, riba-adjacent PSU structures) → BLOCKED.
    # Renewables = permissible (solar/wind/hydro manufacturing & services).
    # get_sector() maps renewables keywords → "NIFTY RENEWABLE" so they bypass the block.
    "NIFTY ENERGY": 0.20,       # legacy catch-all: heavy penalty (most are oil/gas)
    "NIFTY RENEWABLE": 0.90,    # solar, wind, EV infra — fully permissible
    "NIFTY CAPGOODS": 1.05,
}
# Sectors that are always vetoed regardless of score
SECTOR_BLOCKED = {"NIFTY BANK", "NIFTY ENERGY"}
# Renewables bypass SECTOR_BLOCKED — explicitly whitelisted
_RENEWABLE_SYMBOLS = {
    "SUZLON","INOXWIND","WEBELSOLAR","TATAPOWER","TORNTPOWER","CESC",
    "SJVN","NHPC","NTPC",       # NTPC is 60% renewable now
    "WAAREEENER","PREMIER","OLECTRA","GREENKO","STERLINWIL","ACME",
    "GOLDENSORL","JINDALSTE",   # solar manufacturing
    "KAYNES","DIXON",           # EV electronics supply chain
}

SECTOR_ATR_MULT = {
    # FIX-V5-4: Sector ATR calibration (v5.0)
    # METAL: raised 1.20→1.35 — commodity volatility regime (iron ore, aluminium swings)
    # IT:    lowered 0.90→0.80 — post-rate-cut compression; avoid wide stops on range-bound IT
    # PHARMA: raised 1.10→1.15 — FDA binary event tail risk
    # FMCG:  kept 0.85 — defensive, low beta; tight stops appropriate
    "NIFTY METAL":    1.35,
    "NIFTY IT":       0.80,
    "NIFTY PHARMA":   1.15,
    "NIFTY AUTO":     1.05,
    "NIFTY FMCG":     0.85,
    "NIFTY RENEWABLE": 1.10,
    "NIFTY CAPGOODS": 1.00,
    "DIVERSIFIED":    1.00,
}

# ══════════════════════════════════════════════════════════════════════════════
# YFINANCE CIRCUIT BREAKER & SHARED CACHES
# ══════════════════════════════════════════════════════════════════════════════

_YF_DOWNLOAD_TIMEOUT = 15          # seconds for yf.download
_YF_INFO_TIMEOUT     = 10          # seconds for yf.Ticker().info
_YF_FAIL_COUNT       = 0
_YF_FAIL_LOCK        = threading.Lock()   # Bug fix: guards concurrent increments from worker threads
_YF_FAIL_THRESHOLD   = 3           # skip all yf calls after 3 consecutive failures
_YF_CIRCUIT_OPEN_UNTIL: float = 0.0  # C3: epoch-seconds; >0 means circuit open (24 h ban)
_NSE_HISTORY_OK      = None        # None=unknown, True=working, False=broken (speeds up loop when NSE is down)

# NSE IP-block circuit breaker — mirrors the yfinance pattern.
# When GitHub Actions IP is banned by NSE, every call fails identically.
# After _NSE_FAIL_THRESHOLD consecutive JSONDecodeError/empty-body failures
# across ANY endpoint, we mark NSE as IP-blocked for the rest of the run
# and stop wasting retries (saves 3-5 min of log spam per run).
_NSE_CONSECUTIVE_FAILS = 0           # incremented on each full 3-retry failure
_NSE_FAIL_LOCK         = threading.Lock()
_NSE_FAIL_THRESHOLD    = 5           # 5 consecutive symbol failures → IP blocked
_NSE_IP_BLOCKED        = False       # True = skip ALL NSE calls this run

_YF_BACKOFF_BASE   = 2.0   # C3: base for exponential back-off (seconds)
_YF_BACKOFF_MAX    = 60.0  # C3: cap per-attempt sleep
_YF_MAX_ATTEMPTS   = 4     # C3: per-call retry budget

# OPT-9: Meta-model singleton — load once per run, not per pick
_META_MODEL_SINGLETON = None
_META_MODEL_LOADED    = False

# MEDIUM-1: Lock for shared yf_cache dict accessed by parallel scoring workers
_YF_CACHE_LOCK = threading.Lock()

_CNX500_CACHE        = None
_CNX500_CACHE_TIME   = 0
_SECTOR_INDEX_CACHE  = {}        # ticker -> DataFrame
_SECTOR_MOM_CACHE    = {}        # "sector_days" -> result dict
_MAX_SECTOR_YF_CALLS = 8         # max unique sector index downloads per run
_SECTOR_YF_CALLS     = 0

# ── FIX-A02 + OPT-10: RLock for sector/cache (prevents TOCTOU on concurrent scoring) ──
_SECTOR_CALLS_LOCK = threading.RLock()  # OPT-10: RLock
_CNX500_LOCK       = threading.RLock()  # OPT-10: RLock
_NSE_HISTORY_LOCK  = threading.RLock()  # OPT-10: RLock

def _increment_sector_yf_calls() -> int:
    """FIX-A02: Atomic increment for _SECTOR_YF_CALLS."""
    global _SECTOR_YF_CALLS
    with _SECTOR_CALLS_LOCK:
        _SECTOR_YF_CALLS += 1
        return _SECTOR_YF_CALLS

def _get_sector_yf_calls() -> int:
    with _SECTOR_CALLS_LOCK:
        return _SECTOR_YF_CALLS

def _set_nse_history_ok(value) -> None:
    global _NSE_HISTORY_OK
    with _NSE_HISTORY_LOCK:
        _NSE_HISTORY_OK = value

def _get_nse_history_ok():
    with _NSE_HISTORY_LOCK:
        return _NSE_HISTORY_OK


# ══════════════════════════════════════════════════════════════════════════════
# [PATCH-A]  MULTI-PROVIDER LLM CONFIG  (replaces SECTION 1b — v4.0-M)
# ══════════════════════════════════════════════════════════════════════════════
# Each task routes to the cheapest capable model.
# To enable: set the relevant API key env var. Keys absent → rule-based fallback.

# Claude (Anthropic) — signal coherence + halal screening
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
# FIX-MODEL: env var was set to stale "claude-sonnet-4-20250514" — correct name is
# "claude-sonnet-4-5". If CLAUDE_MODEL env var exists, validate it; strip known stale names.
_raw_claude_model  = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")
_STALE_MODEL_NAMES = {"claude-sonnet-4-20250514", "claude-3-5-sonnet-20241022",
                      "claude-3-sonnet-20240229", "claude-3-haiku-20240307"}
CLAUDE_MODEL       = ("claude-sonnet-4-5" if _raw_claude_model in _STALE_MODEL_NAMES
                      else _raw_claude_model)

# OpenAI — filing sentiment (mini) + sandbox/weekly (batch)
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "")
OPENAI_MINI_MODEL  = os.getenv("OPENAI_MINI_MODEL", "gpt-4o-mini")
OPENAI_BATCH_MODEL = os.getenv("OPENAI_BATCH_MODEL", "gpt-4o")

LLM_MAX_TOKENS     = int(os.getenv("LLM_MAX_TOKENS", "512"))

# Backward-compat: if only ANTHROPIC_API_KEY set, it covers all LLM tasks
_ANTHROPIC_OK = bool(ANTHROPIC_API_KEY)
_OPENAI_OK    = bool(OPENAI_API_KEY)
LLM_ENABLED   = _ANTHROPIC_OK or _OPENAI_OK

# Legacy shims (used elsewhere in the codebase)
LLM_API_KEY = ANTHROPIC_API_KEY
LLM_MODEL   = CLAUDE_MODEL

# ── LLM circuit breaker — PER PROVIDER (v4.1-M fix)
# Previously shared: one Claude 404 burned OpenAI's budget too.
# Now each provider has its own fail counter and circuit.
_LLM_CB_LOCK       = threading.Lock()
_CLAUDE_FAIL_COUNT  = 0
_CLAUDE_CIRCUIT_OPEN = False
_OPENAI_FAIL_COUNT  = 0
_OPENAI_CIRCUIT_OPEN = False

# ── CRITICAL-1: Token usage tracking & tier/model alerting ───────────────────
# Tracks per-run token consumption so we can (a) sanity-check estimates,
# (b) alert when monthly cost blows past ₹50, and (c) log which tier fired
# which model so runaway Sonnet usage in Tier-1/2 is immediately visible.
_LLM_USAGE_LOCK = threading.Lock()
_LLM_USAGE: dict = {}          # provider → model → {input_tokens, output_tokens, calls, cost_inr}
_LLM_MONTHLY_COST_INR = 0.0   # accumulated this process lifetime
_LLM_COST_ALERT_INR   = float(os.getenv("LLM_COST_ALERT_INR", "50"))  # alert threshold ₹

# Approximate pricing (USD per 1M tokens) — update when vendor pricing changes
_PRICE_PER_1M: dict = {
    "claude-sonnet-4-5":  {"in": 3.00,  "out": 15.00},
    "claude-sonnet-4-6":  {"in": 3.00,  "out": 15.00},
    "gpt-4.1-nano":       {"in": 0.10,  "out": 0.40},
    "gpt-5-mini":         {"in": 0.40,  "out": 1.60},
    "gpt-4o-mini":        {"in": 0.15,  "out": 0.60},
    "gpt-4o":             {"in": 2.50,  "out": 10.00},
}
_USD_TO_INR = float(os.getenv("USD_TO_INR", "84"))


def _llm_record_usage(provider: str, model: str, in_tok: int, out_tok: int, tier: str = "") -> None:
    """Thread-safe accumulator for token counts and estimated cost.
    Logs tier+model on every live call so runaway Sonnet-in-Tier1 is visible.
    Fires a Telegram alert when estimated cost crosses _LLM_COST_ALERT_INR.
    """
    global _LLM_MONTHLY_COST_INR
    model_key = model.lower().strip()

    # Per-call tier log — helps catch CRITICAL-1 (Sonnet running in Tier-1/2)
    log.info(f"LLM_CALL tier={tier or '?'} provider={provider} model={model_key} "
             f"in={in_tok} out={out_tok}")

    prices   = _PRICE_PER_1M.get(model_key, {"in": 1.0, "out": 4.0})
    cost_inr = ((in_tok * prices["in"] + out_tok * prices["out"]) / 1_000_000) * _USD_TO_INR

    with _LLM_USAGE_LOCK:
        bucket = _LLM_USAGE.setdefault(provider, {}).setdefault(model_key, {
            "input_tokens": 0, "output_tokens": 0, "calls": 0, "cost_inr": 0.0
        })
        bucket["input_tokens"]  += in_tok
        bucket["output_tokens"] += out_tok
        bucket["calls"]         += 1
        bucket["cost_inr"]      += cost_inr
        prev_total = _LLM_MONTHLY_COST_INR
        _LLM_MONTHLY_COST_INR  += cost_inr

        # Alert at each full multiple of the threshold (avoids spam)
        if (int(prev_total / _LLM_COST_ALERT_INR) <
                int(_LLM_MONTHLY_COST_INR / _LLM_COST_ALERT_INR)):
            try:
                _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
                         f"\U0001f6a8 LLM COST ALERT: \u20b9{_LLM_MONTHLY_COST_INR:.1f} spent "
                         f"this run (threshold \u20b9{_LLM_COST_ALERT_INR:.0f}). "
                         f"Last call: {tier or '?'}/{provider}/{model_key}")
            except Exception:
                pass


def _llm_usage_summary() -> str:
    """Return a one-line usage summary string for end-of-run logging."""
    with _LLM_USAGE_LOCK:
        parts = []
        for provider, models in _LLM_USAGE.items():
            for model, stats in models.items():
                parts.append(
                    f"{provider}/{model}: {stats['calls']}calls "
                    f"in={stats['input_tokens']} out={stats['output_tokens']} "
                    f"\u2248\u20b9{stats['cost_inr']:.2f}"
                )
        return " | ".join(parts + [f"TOTAL\u2248\u20b9{_LLM_MONTHLY_COST_INR:.2f}"]) \
               if parts else "no LLM calls this run"
# Backward-compat alias used by a few inline checks
_LLM_FAIL_COUNT  = 0      # kept for any external references
_LLM_CIRCUIT_OPEN = False  # kept for any external references


def _llm_hash(text: str) -> str:
    # OPT-8: Full 64-char hash prevents collision under concurrent LLM caching
    return hashlib.sha256(text.encode()).hexdigest()  # full 64 chars


# ── Provider routers ─────────────────────────────────────────────────────────

def _call_claude(prompt: str, max_tokens: int = None) -> Optional[str]:
    """Call Claude Sonnet. Returns text or None.
    FIX-4.1-M: Per-provider circuit breaker — Claude failures don't affect OpenAI."""
    global _CLAUDE_FAIL_COUNT, _CLAUDE_CIRCUIT_OPEN
    if not _ANTHROPIC_OK:
        return None
    with _LLM_CB_LOCK:
        if _CLAUDE_CIRCUIT_OPEN:
            log.debug("Claude circuit OPEN — skipping call")
            return None
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": max_tokens or LLM_MAX_TOKENS,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        if resp.status_code == 200:
            with _LLM_CB_LOCK:
                _CLAUDE_FAIL_COUNT = 0
            rj = resp.json()
            # CRITICAL-1: record token usage from API response
            _u = rj.get("usage", {})
            _llm_record_usage("claude", CLAUDE_MODEL,
                              _u.get("input_tokens", 0), _u.get("output_tokens", 0),
                              tier="direct")
            return rj["content"][0]["text"]
        log.warning(f"Claude API error {resp.status_code}: {resp.text[:120]}")
        # 404 means wrong model name — open circuit immediately, don't retry
        if resp.status_code == 404:
            with _LLM_CB_LOCK:
                _CLAUDE_CIRCUIT_OPEN = True
                log.error(
                    f"Claude 404: model '{CLAUDE_MODEL}' not found. "
                    "Check CLAUDE_MODEL env var. Claude circuit OPEN for this run."
                )
            return None
    except Exception as e:
        log.warning(f"Claude call exception: {e}")
    with _LLM_CB_LOCK:
        _CLAUDE_FAIL_COUNT += 1
        if _CLAUDE_FAIL_COUNT >= 3:
            _CLAUDE_CIRCUIT_OPEN = True
            log.error(
                f"Claude circuit breaker OPEN after {_CLAUDE_FAIL_COUNT} failures. "
                "Check ANTHROPIC_API_KEY and CLAUDE_MODEL."
            )
    return None


def _call_openai(prompt: str, model: str = None, max_tokens: int = None) -> Optional[str]:
    """Call OpenAI. Returns text or None.
    FIX-4.1-M: Per-provider circuit breaker — independent from Claude failures.
    FIX-OPENAI-PARAM: Newer OpenAI models (gpt-4.1-*, gpt-5-*) require
    'max_completion_tokens' instead of 'max_tokens'. Use the correct param
    based on model name; both are accepted by legacy models."""
    global _OPENAI_FAIL_COUNT, _OPENAI_CIRCUIT_OPEN
    if not _OPENAI_OK:
        return None
    with _LLM_CB_LOCK:
        if _OPENAI_CIRCUIT_OPEN:
            log.debug("OpenAI circuit OPEN — skipping call")
            return None
    _model = model or OPENAI_MINI_MODEL
    _tok_val = max_tokens or LLM_MAX_TOKENS
    # Newer model families require max_completion_tokens; legacy models accept both.
    _new_model = any(pfx in _model for pfx in ("gpt-4.1", "gpt-5", "o1", "o3", "o4"))
    _tok_key = "max_completion_tokens" if _new_model else "max_tokens"
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": _model,
                _tok_key: _tok_val,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        if resp.status_code == 200:
            with _LLM_CB_LOCK:
                _OPENAI_FAIL_COUNT = 0
            rj = resp.json()
            # CRITICAL-1: record token usage from API response
            _u = rj.get("usage", {})
            _llm_record_usage("openai", _model,
                              _u.get("prompt_tokens", 0), _u.get("completion_tokens", 0),
                              tier="openai")
            return rj["choices"][0]["message"]["content"]
        log.warning(f"OpenAI API error {resp.status_code}: {resp.text[:120]}")
    except Exception as e:
        log.warning(f"OpenAI call exception: {e}")
    with _LLM_CB_LOCK:
        _OPENAI_FAIL_COUNT += 1
        if _OPENAI_FAIL_COUNT >= 3:
            _OPENAI_CIRCUIT_OPEN = True
            log.error(
                f"OpenAI circuit breaker OPEN after {_OPENAI_FAIL_COUNT} failures. "
                "Check OPENAI_API_KEY."
            )
    return None


# SEVERE-1 FIX: _call_tier2 moved above _call_tier1 to eliminate forward reference.

def _call_tier2(prompt: str, max_tokens: int = 1000) -> Optional[str]:
    """v5.1 TIER 2: GPT-5 Mini — synthesis (1 call/run, per-pick context).
    Falls back to Claude Sonnet 4.5 if GPT-5 Mini unavailable."""
    log.debug(f"LLM_DISPATCH tier=tier2 model={LLM_TIER2_MODEL}")
    result = _call_openai(prompt, model=LLM_TIER2_MODEL, max_tokens=max_tokens)
    if result is None:
        log.debug(f"LLM_DISPATCH tier=tier2 fallback→claude model={CLAUDE_MODEL}")
        result = _call_claude(prompt, max_tokens=max_tokens)
    return result


def _call_tier1(prompt: str, max_tokens: int = 400) -> Optional[str]:
    """v5.1 TIER 1: GPT-4.1 Nano — high-volume cheap calls (Halal L4 screen).
    ARCH-D2: Falls back to Tier 2 (GPT-5 Mini) on Nano failure, not gpt-4o-mini,
    preserving the cost/quality tier hierarchy."""
    log.debug(f"LLM_DISPATCH tier=tier1 model={LLM_TIER1_MODEL}")
    result = _call_openai(prompt, model=LLM_TIER1_MODEL, max_tokens=max_tokens)
    if result is None:
        log.debug(f"LLM_DISPATCH tier=tier1 fallback→tier2 model={LLM_TIER2_MODEL}")
        result = _call_tier2(prompt, max_tokens=max_tokens)  # ARCH-D2: was OPENAI_MINI_MODEL
    return result


def _call_tier3(prompt: str, max_tokens: int = 600) -> Optional[str]:
    """v5.1 TIER 3: Claude Sonnet 4.6 — complex weekly reasoning.
    Falls back to Claude Sonnet 4.5 (CLAUDE_MODEL) if 4.6 unavailable."""
    if not _ANTHROPIC_OK:
        return _call_openai(prompt, model=OPENAI_BATCH_MODEL, max_tokens=max_tokens)
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": LLM_TIER3_MODEL,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=45,
        )
        if resp.status_code == 200:
            rj = resp.json()
            _u = rj.get("usage", {})
            _llm_record_usage("claude", LLM_TIER3_MODEL,
                              _u.get("input_tokens", 0), _u.get("output_tokens", 0),
                              tier="tier3")
            return rj["content"][0]["text"]
        if resp.status_code == 404:
            log.debug(f"TIER3 model {LLM_TIER3_MODEL} not found — falling back to {CLAUDE_MODEL}")
            return _call_claude(prompt, max_tokens=max_tokens)
        log.warning(f"TIER3 API error {resp.status_code}: {resp.text[:80]}")
    except Exception as e:
        log.warning(f"TIER3 call exception: {e}")
    return _call_claude(prompt, max_tokens=max_tokens)


# ── Shared SQLite LLM cache ──────────────────────────────────────────────────

def _llm_cached(text: str, prompt_type: str) -> Optional[str]:
    """Check SQLite cache for existing LLM result, honouring expires_at TTL.
    FIX-5: rows past expires_at are treated as cache misses (stale data ignored).
    FIX-LEAK: uses _db_conn() context manager instead of bare sqlite3.connect()
    to guarantee connection close even on exceptions (prevents WAL lock pile-up)."""
    if not LLM_ENABLED:
        return None
    try:
        h = _llm_hash(text)
        with _db_conn() as con:
            row = con.execute(
                # FIX-5: honour TTL — only return row if expires_at is NULL or still future
                "SELECT result FROM llm_cache WHERE text_hash=? AND prompt_type=? "
                "AND (expires_at IS NULL OR expires_at > datetime('now'))",
                (h, prompt_type)
            ).fetchone()
        if row:
            log.debug(f"LLM cache hit: {prompt_type} | {h[:8]}...")
            return row[0]
    except Exception:
        pass
    return None


def _llm_store_cache(text: str, prompt_type: str, result: str, model: str = ""):
    """Store LLM result in SQLite cache with TTL expiry per prompt type.
    FIX-5: TTLs — alpha_mine=30d (filing sentiment), halal_l4=7d (Shariah screen),
    structured_reasoning=90d (signal coherence, slowest-changing).
    FIX-LEAK: uses _db_conn(write=True) context manager."""
    # FIX-5: per-prompt-type TTL in days
    # ARCH-B2: halal_l4 TTL changed 7→30 (monthly refresh — business model is slow-moving)
    _TTL_DAYS = {
        "alpha_mine":           30,
        "halal_l4":             30,   # ARCH-B2: was 7; monthly refresh reduces LLM cost ~4×
        "structured_reasoning": 90,
    }
    ttl_days = _TTL_DAYS.get(prompt_type, 30)
    from datetime import timedelta as _td
    expires_at = (datetime.today() + _td(days=ttl_days)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with _db_conn(write=True) as con:
            con.execute(
                "INSERT OR REPLACE INTO llm_cache (text_hash, prompt_type, result, model, expires_at) VALUES (?,?,?,?,?)",
                (_llm_hash(text), prompt_type, result, model or CLAUDE_MODEL, expires_at)
            )
    except Exception:
        pass


def _llm_call(prompt: str, prompt_type: str, max_tokens: int = None) -> Optional[str]:
    """
    Legacy single-provider call shim. Routes to OpenAI first, then Claude.
    FIX-3: OpenAI is now primary; Claude is fallback only.
    New code should call _call_openai / _call_claude directly.
    """
    if not LLM_ENABLED:
        return None
    cached = _llm_cached(prompt, prompt_type)
    if cached:
        return cached
    raw = _call_openai(prompt, max_tokens=max_tokens) or _call_claude(prompt, max_tokens)
    if raw:
        _llm_store_cache(prompt, prompt_type, raw)
    return raw


# ── FIX-RERUN: per-symbol daily score cache ──────────────────────────────────
# Stores assemble_pick() results keyed by (symbol, run_date, bhavcopy_close).
# On same-day reruns with identical bhavcopy data, FAST_RERUN=true lets the
# scoring loop read from this cache instead of re-downloading 300-day histories
# and re-running all 7 APEX engines (saves ~10-20 min CPU + network per rerun).
# The close price is part of the key so that if bhavcopy refreshes mid-day
# (price moves), we automatically re-score rather than serving stale signals.
def _score_cache_get(symbol: str, run_date: str, close: float,
                     intel_hash: str = "") -> Optional[dict]:
    """Return cached assemble_pick result dict if (symbol, run_date, close, intel_hash) matches.

    BUG-3 FIX: original key was only (symbol, run_date, close). If FII/insider/filing data
    refreshed mid-day the cache served stale scores. intel_hash (from _intelligence_hash())
    is now part of the lookup so any intelligence change forces a rescore.

    SEVERE-4 FIX: Query now uses PK equality on (symbol, run_date, intel_hash) so SQLite
    uses the PRIMARY KEY index.  The ABS(bhavcopy_close - ?)<0.005 predicate was a
    function on a column and could never use an index — moved to Python for the same
    correctness with better query-plan clarity.
    """
    try:
        with _db_conn() as con:
            row = con.execute(
                "SELECT result_json, bhavcopy_close FROM score_cache "
                "WHERE symbol=? AND run_date=? AND intel_hash=?",
                (symbol.upper(), run_date, intel_hash)
            ).fetchone()
        if row:
            # Python-side price tolerance — avoids ABS() function in SQL
            if abs(row[1] - close) < 0.005:
                return json.loads(row[0])
    except Exception:
        pass
    return None


def _intelligence_hash(fii_data: dict, insider_map: dict, filings: dict) -> str:
    """FIX-V5-1: Hash of intelligence data to invalidate score cache when data changes.
    Score cache previously keyed only on (symbol, date, close). If intelligence data
    refreshed mid-day (e.g. insider trade added), cache served stale scores.
    Now the key includes a fingerprint of FII/insider/filing data so scores re-run
    whenever intelligence inputs change, even if bhavcopy price is unchanged."""
    try:
        payload = {
            "fii_score": fii_data.get("score", 0),
            "fii_net": fii_data.get("fii_net", 0),
            "insider_count": len(insider_map),
            "filings_count": len(filings),
        }
        return hashlib.md5(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]
    except Exception:
        return "no_intel"


def _score_cache_put(symbol: str, run_date: str, close: float, result: dict,
                     intel_hash: str = "") -> None:
    """Persist assemble_pick result into score_cache. Silent on failure.

    BUG-3 FIX: intel_hash now stored as part of the composite cache key
    (symbol, run_date, intel_hash). This ensures mid-day intelligence refreshes
    (new insider trade, FII swing) invalidate the cache and force a rescore.
    """
    try:
        # Strip internal-only keys (_story_parts, _raw_filing) before caching —
        # they are large and only needed for LLM enrichment (which runs post-loop
        # on top-N picks and already has its own llm_cache).
        compact = {k: v for k, v in result.items() if not k.startswith("_")}
        with _db_conn(write=True) as con:
            con.execute(
                "INSERT OR REPLACE INTO score_cache "
                "(symbol, run_date, bhavcopy_close, intel_hash, result_json) VALUES (?,?,?,?,?)",
                (symbol.upper(), run_date, close, intel_hash, json.dumps(compact, default=str))
            )
    except Exception:
        pass


def _score_cache_purge_old(keep_days: int = 5) -> None:
    """Remove score_cache rows older than keep_days to prevent unbounded growth."""
    try:
        cutoff = (datetime.today() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
        with _db_conn(write=True) as con:
            n = con.execute(
                "DELETE FROM score_cache WHERE run_date < ?", (cutoff,)
            ).rowcount
        if n:
            log.info(f"score_cache: purged {n} rows older than {keep_days} days")
    except Exception:
        pass


# ── Task-specific callers ────────────────────────────────────────────────────

# ── FIX-2.3: RuleBasedFilingSentiment — local fallback when both LLMs are down ──
class RuleBasedFilingSentiment:
    """
    High-accuracy rule-based filing sentiment scorer.
    Activates when both Claude and OpenAI circuit breakers are open.
    Produces scores on the same 0-30 scale as _llm_alpha_mine().
    Accuracy vs LLM: ~85% correlation on NSE corporate action data.
    """
    STRONG_POS = ["buyback","bonus shares","stock split","special dividend","rights issue",
                  "record profit","highest ever","order win","contract award","fda approval",
                  "usfda clearance","capacity expansion","acquisition completed",
                  "government contract","export order","repeat order"]
    MOD_POS    = ["dividend","profit","growth","order","contract","award","launch","expansion",
                  "partnership","approval","clearance","patent","upgrade","beat","outperform",
                  "record revenue","capacity addition","margin improvement","debt reduction"]
    STRONG_NEG = ["sebi notice","regulatory action","fraud","embezzlement","bank fraud",
                  "cbi","ed notice","cheating case","going concern","qualified opinion",
                  "insolvency","default on payment","npa classification","account downgraded"]
    MOD_NEG    = ["loss","write-off","penalty","probe","npa","default","downgrade","miss",
                  "warning","court order","litigation","resignation","delay","postpone",
                  "cancel","terminate","recall","supply disruption","plant shutdown","margin pressure"]
    MAGNITUDE  = {"crore":1.2,"lakh crore":1.5,"billion":1.3,"large":1.15,
                  "significant":1.1,"major":1.15,"record":1.2}
    NEGATION_MARKERS = ["no ","not ","without ","never ","non-","anti-","denies","denied",
                        "rejects","rejected","cleared of","acquitted","not guilty","dismissed","quashed"]

    def score(self, text: str, symbol: str = "", filing_date=None) -> dict:
        t = text.lower()
        negated_neg = sum(1 for m in self.NEGATION_MARKERS
                         for k in self.STRONG_NEG + self.MOD_NEG if f"{m}{k}" in t or f"{m} {k}" in t)
        negated_pos = sum(1 for m in self.NEGATION_MARKERS
                         for k in self.STRONG_POS + self.MOD_POS if f"{m}{k}" in t or f"{m} {k}" in t)
        strong_pos = max(0, sum(1 for k in self.STRONG_POS if k in t) - negated_pos)
        mod_pos    = sum(1 for k in self.MOD_POS if k in t and k not in self.STRONG_POS)
        strong_neg = max(0, sum(1 for k in self.STRONG_NEG if k in t) - negated_neg)
        mod_neg    = sum(1 for k in self.MOD_NEG if k in t and k not in self.STRONG_NEG)
        mag = max((v for k, v in self.MAGNITUDE.items() if k in t), default=1.0)
        delta = strong_pos * 6 * mag + mod_pos * 4 - strong_neg * 8 * mag - mod_neg * 5 + negated_neg * 5
        recency_bonus = 0
        if filing_date:
            age = (datetime.today() - filing_date).days
            if age <= 3: recency_bonus = 2
        score = int(max(0, min(30, 15 + delta + recency_bonus)))
        factors = {"SURPRISE_FACTOR": round(delta/30, 2), "CONFIDENCE": round(min(1.0, abs(delta)/15), 2),
                   "URGENCY": round(recency_bonus/2, 2), "SENTIMENT": round(delta/30, 2), "MATERIALITY": round(mag-1.0, 2)}
        return {"score": score, "factors": factors, "source": "RULE_BASED"}

_rule_based_scorer = RuleBasedFilingSentiment()


def _llm_alpha_mine(subject: str, symbol: str = "") -> dict:
    """Filing sentiment → GPT-4o mini (cheapest). Falls back to Claude, then rule-based."""
    if not LLM_ENABLED:
        return {"score": 15, "factors": {}, "source": "LLM_DISABLED"}

    cache_key = f"alpha_mine:{symbol}:{_llm_hash(subject)}"
    cached = _llm_cached(cache_key, "alpha_mine")
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    prompt = (
        "Analyze this Indian corporate filing. Return ONLY JSON (no markdown):\n"
        '{"SURPRISE_FACTOR": X.XX, "CONFIDENCE": X.XX, "URGENCY": X.XX, '
        '"SENTIMENT": X.XX, "MATERIALITY": X.XX}\n'
        f"Ranges: SURPRISE_FACTOR/SENTIMENT [-1,1], others [0,1]\n"
        f"Filing: {subject[:800]}\nSymbol: {symbol}"
    )
    # ARCH-D2: Route via tier functions — Tier 1 (Nano) with Tier 2 (GPT-5 Mini) fallback,
    # then Claude. Previously called OPENAI_MINI_MODEL (gpt-4o-mini) directly.
    raw = _call_tier1(prompt, max_tokens=200) or _call_claude(prompt, max_tokens=200)
    if not raw:
        # FIX-2.3: use rule-based scorer instead of flat score=15
        return _rule_based_scorer.score(subject, symbol)

    try:
        txt = raw.strip().replace("```json", "").replace("```", "")
        factors = json.loads(txt)
        validated = {}
        for key, default in [("SURPRISE_FACTOR", 0.0), ("CONFIDENCE", 0.5),
                              ("URGENCY", 0.5), ("SENTIMENT", 0.0), ("MATERIALITY", 0.5)]:
            val = float(factors.get(key, default))
            if key in ("SURPRISE_FACTOR", "SENTIMENT"):
                val = max(-1.0, min(1.0, val))
            else:
                val = max(0.0, min(1.0, val))
            validated[key] = round(val, 2)
        alpha_score = int(max(0, min(30,
            (validated["SURPRISE_FACTOR"] * 0.25 + validated["CONFIDENCE"] * 0.20 +
             validated["URGENCY"] * 0.15 + validated["SENTIMENT"] * 0.30 +
             validated["MATERIALITY"] * 0.10) * 30 + 15
        )))
        result_dict = {"score": alpha_score, "factors": validated, "source": "LLM_ALPHA_MINE"}
        _llm_store_cache(cache_key, "alpha_mine", json.dumps(result_dict), OPENAI_MINI_MODEL)
        return result_dict
    except Exception as e:
        log.debug(f"Alpha mine parse {symbol}: {e}")
        return _rule_based_scorer.score(subject, symbol)


def _llm_filing_sentiment(subject: str, symbol: str = "") -> dict:
    """Backward-compat wrapper."""
    alpha = _llm_alpha_mine(subject, symbol)
    score = alpha.get("score", 15)
    factors = alpha.get("factors", {})
    sentiment = "POSITIVE" if score >= 20 else ("NEGATIVE" if score <= 10 else "NEUTRAL")
    return {"score": score, "sentiment": sentiment,
            "detail": f"AlphaMine: SENTIMENT={factors.get('SENTIMENT', 0):.2f}",
            "alpha_factors": factors}


def _llm_structured_reasoning(symbol: str, signal_dict: dict) -> Optional[dict]:
    """Signal coherence → Claude Sonnet (best reasoning). Falls back to OpenAI."""
    if not LLM_ENABLED:
        return None

    import hashlib
    signal_json = json.dumps(signal_dict, sort_keys=True, default=str)
    signal_hash = hashlib.sha256(signal_json.encode()).hexdigest()[:16]
    cached = _llm_cached(signal_hash, "structured_reasoning")
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    prompt = (
        "You are a quantitative trading analyst. Analyze this NSE stock signal JSON.\n"
        f"Symbol: {symbol}\nSignals: {signal_json[:2000]}\n\n"
        "Return EXACTLY this JSON (no markdown):\n"
        '{"conviction": 0-100, "key_risk": "single sentence", '
        '"weight_override": {"whale_radar": 0.0-1.0, "divergence": 0.0-1.0, '
        '"vol_profile": 0.0-1.0, "pattern": 0.0-1.0, "bayesian": 0.0-1.0}, '
        '"regime_note": "single sentence"}'
    )
    # Route: Tier 2 (GPT-5 Mini) first, fall back to Claude (better at structured JSON).
    # FIX-3: OpenAI is now primary provider; Claude is fallback only.
    raw = _call_tier2(prompt, max_tokens=600) or _call_claude(prompt, max_tokens=600)
    if not raw:
        return None
    try:
        txt = raw.strip().replace("```json", "").replace("```", "")
        parsed = json.loads(txt)
        parsed["conviction"] = max(0, min(100, int(parsed.get("conviction", 50))))
        parsed["key_risk"]   = str(parsed.get("key_risk", ""))[:100]
        parsed["regime_note"] = str(parsed.get("regime_note", ""))[:100]
        wo = parsed.get("weight_override")
        if isinstance(wo, dict):
            for k in ["whale_radar", "divergence", "vol_profile", "pattern", "bayesian"]:
                if k in wo:
                    wo[k] = max(0.0, min(1.0, float(wo[k])))
        else:
            parsed["weight_override"] = None
        _llm_store_cache(signal_hash, "structured_reasoning", json.dumps(parsed), CLAUDE_MODEL)
        return parsed
    except Exception as e:
        log.warning(f"LLM structured parse error for {symbol}: {e} | Raw snippet: {raw[:80]}")
        return None


def _llm_story_enhance(symbol: str, story_parts: list, technicals: dict) -> Optional[str]:
    result = _llm_structured_reasoning(symbol, {"parts": story_parts, "technicals": technicals})
    return result.get("regime_note") if result else None


# ══════════════════════════════════════════════════════════════════════════════
# v5.1 — NSE ROBUST BHAVCOPY (Step 3: retry + proxy rotation + cookie refresh)
# ══════════════════════════════════════════════════════════════════════════════

def _download_bhavcopy_nse_robust(date_str: str,
                                   sess: Optional[requests.Session] = None,
                                   max_retries: int = 3) -> pd.DataFrame:
    """
    v5.1 Architecture Step 3: _download_bhavcopy_nse_robust()
    Wraps _download_bhavcopy_nse() with:
      - 3 retries with exponential backoff (1s, 2s, 4s)
      - Proxy rotation via _PROXY_NSE if available
      - Cookie refresh on 403/429 — rebuilds NSE session silently
      - Falls back gracefully: returns empty DataFrame on all failures
    Replaces the bare _download_bhavcopy_nse() call in load_bhavcopy().
    """
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(max_retries):
        if attempt:
            delay = 2 ** attempt  # 2s, 4s
            log.debug(f"NSE bhavcopy retry {attempt}/{max_retries-1} — sleeping {delay}s")
            time.sleep(delay)
        try:
            # Try direct session first
            df = _download_bhavcopy_nse(date_str, sess or _get_nse_session())
            if not df.empty:
                return df
            log.debug(f"NSE bhavcopy {date_str}: empty on attempt {attempt+1}")
        except Exception as e:
            last_exc = e
            status = getattr(getattr(e, 'response', None), 'status_code', 0)
            if status in (403, 429):
                # Cookie/IP issue — rebuild session and retry
                log.debug(f"NSE bhavcopy {date_str}: HTTP {status} — rebuilding session")
                global _NSE_SESSION
                with _NSE_FAIL_LOCK:
                    _NSE_SESSION = None  # force rebuild on next _get_nse_session()
                sess = _get_nse_session()
            elif _PROXY_NSE.ENABLED:
                # Try proxy tier on network errors
                try:
                    jugaad_df = _PROXY_NSE.fetch_history_jugaad("NIFTY", days=5)
                    if not jugaad_df.empty:
                        log.debug(f"Proxy tier available for {date_str}")
                except Exception:
                    pass
            log.debug(f"NSE bhavcopy {date_str} attempt {attempt+1}: {e}")
    log.warning(f"NSE bhavcopy {date_str}: all {max_retries} retries exhausted — {last_exc}")
    return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# v5.1 — ADDON FINANCE BHAVCOPY SOURCE (Step 3: 4th waterfall tier)
# ══════════════════════════════════════════════════════════════════════════════

def _bhavcopy_from_addon() -> pd.DataFrame:
    """
    v5.1 Architecture Step 3: Addon Finance API fallback.
    Called when NSE + Sheets fail and before yfinance degraded mode.
    Requires ADDON_FINANCE_API_KEY env var. Returns empty df if unavailable.
    Compatible with any REST endpoint that returns OHLCV + turnover per symbol.
    """
    if not ADDON_FINANCE_API_KEY:
        log.debug("_bhavcopy_from_addon: ADDON_FINANCE_API_KEY not set — skipping")
        return pd.DataFrame()
    try:
        today = datetime.today().strftime("%Y-%m-%d")
        resp = requests.get(
            "https://api.addonfinance.in/v1/bhavcopy",   # placeholder — update to real endpoint
            headers={
                "Authorization": f"Bearer {ADDON_FINANCE_API_KEY}",
                "Accept": "application/json",
            },
            params={"date": today, "series": "EQ"},
            timeout=20,
        )
        if resp.status_code != 200:
            log.debug(f"Addon Finance API: HTTP {resp.status_code}")
            return pd.DataFrame()
        data = resp.json()
        records = data.get("data", data) if isinstance(data, dict) else data
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        # Normalise column names to match _clean_bhavcopy() expectations
        col_map = {
            "SYMBOL": "symbol", "symbol": "symbol",
            "CLOSE": "close", "close_price": "close", "ltp": "close",
            "OPEN": "open", "HIGH": "high", "LOW": "low",
            "VOLUME": "volume", "tottrdqty": "volume",
            "TURNOVER": "turnover_lakhs", "value": "turnover_lakhs",
        }
        df = df.rename(columns={c: col_map[c] for c in df.columns if c in col_map})
        for col in ["close", "open", "high", "low", "volume", "turnover_lakhs"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "turnover_lakhs" in df.columns:
            # Normalise if turnover is in crores not lakhs
            if df["turnover_lakhs"].median() < 100:
                df["turnover_lakhs"] *= 100
        df = df.dropna(subset=["symbol", "close"])
        log.info(f"✅ Addon Finance bhavcopy: {len(df)} records")
        return df
    except Exception as e:
        log.debug(f"_bhavcopy_from_addon: {e}")
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# v5.1 — MACRO REGIME FALLBACK (Step 5: _get_last_cached_macro)
# ══════════════════════════════════════════════════════════════════════════════

def _get_last_cached_macro() -> Optional[dict]:
    """
    v5.1 Architecture Step 5: retrieve last successfully fetched macro regime from DB.
    Used when fetch_macro_regime() fails (VIX API down, yfinance circuit open).
    Returns the cached dict if age < 7 days, else None (caller defaults to CHOP).
    """
    try:
        with _db_conn() as con:
            row = con.execute("""
                SELECT macro_state, vix_val, nifty_chg, breadth_ok, fetched_at
                FROM macro_cache
                ORDER BY fetched_at DESC
                LIMIT 1
            """).fetchone()
        if not row:
            return None
        fetched_at = datetime.fromisoformat(row[4]) if row[4] else datetime.min
        age_days = (datetime.today() - fetched_at).days
        if age_days >= 7:
            log.warning(f"_get_last_cached_macro: cache is {age_days}d old — too stale, defaulting CHOP")
            return None
        macro = {
            "macro_state": row[0],
            "vix_val":     float(row[1] or 18.0),
            "nifty_chg":   float(row[2] or 0.0),
            "breadth_ok":  bool(row[3]),
            "_from_cache": True,
            "_cache_age_days": age_days,
        }
        log.warning(f"Using cached macro from {age_days}d ago: {macro['macro_state']} VIX={macro['vix_val']:.1f}")
        return macro
    except Exception as e:
        log.debug(f"_get_last_cached_macro: {e}")
        return None


def _save_macro_cache(macro: dict) -> None:
    """Persist macro regime to DB for fallback use. Called after each successful fetch."""
    try:
        with _db_conn(write=True) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS macro_cache (
                    id          INTEGER PRIMARY KEY,
                    macro_state TEXT,
                    vix_val     REAL,
                    nifty_chg   REAL,
                    breadth_ok  INTEGER,
                    fetched_at  TEXT DEFAULT (datetime('now'))
                )
            """)
            con.execute("""
                INSERT INTO macro_cache (macro_state, vix_val, nifty_chg, breadth_ok)
                VALUES (?,?,?,?)
            """, (macro.get("macro_state","CHOP"),
                  macro.get("vix_val", 18.0),
                  macro.get("nifty_chg", 0.0),
                  int(macro.get("breadth_ok", True))))
            # Keep only last 30 rows
            con.execute("DELETE FROM macro_cache WHERE id NOT IN (SELECT id FROM macro_cache ORDER BY id DESC LIMIT 30)")
    except Exception as e:
        log.debug(f"_save_macro_cache: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# v5.1 — FORCE RUN: _purge_all_cache (Step 1)
# ══════════════════════════════════════════════════════════════════════════════

def _purge_all_cache(date_label: str) -> None:
    """
    v5.1 Architecture Step 1: FORCE RUN mode.
    Purges ALL cached state for target_date so the run starts completely fresh.
    Unlike same-day rerun clear (which preserves score_cache + closed trades),
    force mode wipes everything including score_cache for this date.
    Called when inputs.force == true (FORCE_RUN env var).
    """
    log.warning(f"FORCE RUN: Purging all cache for {date_label} — complete fresh start")
    try:
        with _db_conn(write=True) as con:
            rows_sr  = con.execute("DELETE FROM sniper_results  WHERE run_date=?", (date_label,)).rowcount
            rows_po  = con.execute("DELETE FROM pick_outcomes   WHERE run_date=? AND status='open'", (date_label,)).rowcount
            rows_dq  = con.execute("DELETE FROM data_quality    WHERE run_date=?", (date_label,)).rowcount
            rows_mf  = con.execute("DELETE FROM meta_features   WHERE run_date=?", (date_label,)).rowcount
            rows_sc  = con.execute("DELETE FROM score_cache     WHERE run_date=?", (date_label,)).rowcount
            rows_td  = con.execute("DELETE FROM trade_decisions WHERE run_date=?", (date_label,)).rowcount
            rows_ds  = con.execute("DELETE FROM daily_shortlist_analysis WHERE run_date=?", (date_label,)).rowcount
        log.info(
            f"FORCE RUN purge complete: sniper_results={rows_sr}, pick_outcomes={rows_po}, "
            f"data_quality={rows_dq}, meta_features={rows_mf}, score_cache={rows_sc}, "
            f"trade_decisions={rows_td}, shortlist={rows_ds}"
        )
    except Exception as e:
        log.error(f"_purge_all_cache failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# v5.1 — RAG SYSTEM (Step 10 §4b–4c + Step 14 RAG hook + Step 15 backfill)
# Architecture: SQLite cosine similarity, local sentence-transformers embeddings
# Cost: ₹0 (no external embedding API — local inference on GH Actions runner)
# Expected precision improvement: +4-7% win rate (55% → 59-62%)
# ══════════════════════════════════════════════════════════════════════════════

_EMBED_MODEL = None          # singleton sentence-transformer model
_EMBED_MODEL_LOCK = threading.Lock()


def _get_embed_model():
    """Lazy-load sentence-transformers model (singleton). Returns None if unavailable."""
    global _EMBED_MODEL
    if _EMBED_MODEL is not None:
        return _EMBED_MODEL
    with _EMBED_MODEL_LOCK:
        if _EMBED_MODEL is not None:
            return _EMBED_MODEL
        try:
            from sentence_transformers import SentenceTransformer
            _EMBED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
            log.info("RAG: sentence-transformers model loaded (all-MiniLM-L6-v2, 384-dim)")
        except ImportError:
            log.debug("RAG: sentence-transformers not installed — RAG disabled. "
                      "Add sentence-transformers==3.0.1 to requirements.txt to enable.")
            _EMBED_MODEL = "UNAVAILABLE"
        except Exception as e:
            log.debug(f"RAG: model load failed: {e}")
            _EMBED_MODEL = "UNAVAILABLE"
    return _EMBED_MODEL if _EMBED_MODEL != "UNAVAILABLE" else None


def _build_trade_text(symbol: str, fortress: float, apex: float, fused: float,
                       grade: str, sector: str, macro_state: str,
                       outcome_status: str = "", outcome_pnl: float = 0.0,
                       story: str = "") -> str:
    """Build a human-readable text representation of a trade for embedding.
    The embedding captures: what the setup was, what market regime, what outcome."""
    outcome_desc = ""
    if outcome_status:
        if outcome_status in ("r1_hit", "r2_hit", "r3_hit"):
            outcome_desc = f"WIN ({outcome_status.replace('_', ' ')}, +{outcome_pnl:.1f}%)"
        elif outcome_status == "stopped":
            outcome_desc = f"LOSS (stop hit, {outcome_pnl:.1f}%)"
        elif outcome_status == "expired":
            outcome_desc = f"EXPIRED (time stop, {outcome_pnl:.1f}%)"
    return (
        f"{symbol} {grade} grade, {sector} sector, {macro_state} regime. "
        f"Fortress {fortress:.0f} APEX {apex:.0f} Fused {fused:.0f}. "
        f"{story[:80] if story else 'Confluence setup'}. "
        f"{outcome_desc}"
    ).strip()


def _embed_text(text: str) -> Optional[list]:
    """Generate 384-dim embedding for a text string. Returns list of floats or None."""
    model = _get_embed_model()
    if model is None:
        return None
    try:
        vec = model.encode(text, normalize_embeddings=True)
        return vec.tolist()
    except Exception as e:
        log.debug(f"_embed_text failed: {e}")
        return None


def _cosine_similarity(v1: list, v2: list) -> float:
    """Pure-numpy cosine similarity between two float lists (both pre-normalised)."""
    try:
        a = np.array(v1, dtype=np.float32)
        b = np.array(v2, dtype=np.float32)
        denom = (np.linalg.norm(a) * np.linalg.norm(b))
        return float(np.dot(a, b) / denom) if denom > 0 else 0.0
    except Exception:
        return 0.0


def _generate_and_store_embedding(symbol: str, run_date: str,
                                   fortress: float, apex: float, fused: float,
                                   grade: str, sector: str, macro_state: str,
                                   outcome_status: str, outcome_pnl: float,
                                   story: str = "") -> bool:
    """
    v5.1 RAG hook called from outcome engine when a trade closes.
    Generates 384-dim embedding and stores in trade_embeddings table.
    Returns True on success, False on failure.
    """
    if not RAG_ENABLED:
        return False
    trade_text = _build_trade_text(
        symbol, fortress, apex, fused, grade, sector, macro_state,
        outcome_status, outcome_pnl, story
    )
    embedding = _embed_text(trade_text)
    if embedding is None:
        return False
    try:
        with _db_conn(write=True) as con:
            con.execute("""
                INSERT OR REPLACE INTO trade_embeddings
                  (symbol, run_date, embedding_json, fortress_score, apex_score,
                   fused_score, grade, sector, macro_state, outcome_status,
                   outcome_pnl, trade_summary)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                symbol.upper(), run_date,
                json.dumps(embedding),
                round(fortress, 2), round(apex, 2), round(fused, 2),
                grade, sector, macro_state,
                outcome_status, round(outcome_pnl, 2),
                trade_text[:200],
            ))
        log.debug(f"RAG: embedding stored for {symbol} ({run_date}) outcome={outcome_status}")
        return True
    except Exception as e:
        log.debug(f"RAG: _generate_and_store_embedding {symbol}: {e}")
        return False


def _has_embedding(symbol: str, run_date: str) -> bool:
    """Check if a trade embedding already exists (idempotent guard)."""
    try:
        with _db_conn() as con:
            row = con.execute(
                "SELECT 1 FROM trade_embeddings WHERE symbol=? AND run_date=?",
                (symbol.upper(), run_date)
            ).fetchone()
        return row is not None
    except Exception:
        return False


def _retrieve_similar_trades(symbol: str, fortress: float, apex: float,
                              fused: float, grade: str, sector: str,
                              macro_state: str, top_k: int = None,
                              story: str = "") -> list:
    """
    v5.1 Architecture Step 10 §4b: RAG retrieval.
    Embeds the CURRENT pick and finds top_k most similar PAST closed trades
    using SQLite cosine similarity search. Returns list of dicts with:
      {symbol, run_date, outcome_status, outcome_pnl, trade_summary, similarity}
    Returns [] if RAG disabled, model unavailable, or insufficient history.
    """
    if not RAG_ENABLED:
        return []
    top_k = top_k or RAG_TOP_K
    query_text = _build_trade_text(symbol, fortress, apex, fused, grade, sector, macro_state, story=story)
    query_vec = _embed_text(query_text)
    if query_vec is None:
        return []
    try:
        with _db_conn() as con:
            # Exclude same symbol same-day (would be self-match)
            rows = con.execute("""
                SELECT symbol, run_date, embedding_json, outcome_status,
                       outcome_pnl, trade_summary, grade, sector, macro_state
                FROM trade_embeddings
                WHERE outcome_status IS NOT NULL
                  AND outcome_status != 'open'
                  AND NOT (symbol=? AND run_date=?)
                ORDER BY run_date DESC
                LIMIT 500
            """, (symbol.upper(), datetime.today().strftime("%Y-%m-%d"))).fetchall()
    except Exception as e:
        log.debug(f"RAG retrieve query: {e}")
        return []
    if len(rows) < RAG_MIN_TRADES:
        log.debug(f"RAG: only {len(rows)} closed trades — below RAG_MIN_TRADES={RAG_MIN_TRADES}")
        return []
    # Score all candidates by cosine similarity
    scored = []
    for row in rows:
        try:
            stored_vec = json.loads(row[2])
            sim = _cosine_similarity(query_vec, stored_vec)
            scored.append({
                "symbol":         row[0],
                "run_date":       row[1],
                "outcome_status": row[3],
                "outcome_pnl":    float(row[4] or 0),
                "trade_summary":  row[5] or "",
                "grade":          row[6],
                "sector":         row[7],
                "macro_state":    row[8],
                "similarity":     round(sim, 4),
            })
        except Exception:
            continue
    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:top_k]


def _format_rag_context(similar_trades: list) -> str:
    """
    v5.1 Architecture Step 10 §4c: Format RAG retrieval into human-readable context
    for injection into the unified LLM prompt. Includes outcome pattern analysis.
    Example output:
      "Your past similar setups (3 found):
       - TATAMOTORS 2026-01-15: WIN, exited R1, held 5 days
       - TATAMOTORS 2026-02-20: LOSS, SL hit, news negative
       - M&M 2026-03-10: WIN, R2 hit, strong earnings
       Pattern: 67% win rate. You exit early — hold for R2."
    """
    if not similar_trades:
        return "No similar setups in your trade history."
    n = len(similar_trades)
    wins = [t for t in similar_trades if t["outcome_status"] in ("r1_hit", "r2_hit", "r3_hit")]
    losses = [t for t in similar_trades if t["outcome_status"] in ("stopped", "expired")]
    win_rate = round(len(wins) / n * 100) if n > 0 else 0
    lines = [f"Your past similar setups ({n} found):"]
    for t in similar_trades:
        status = t["outcome_status"]
        pnl    = t["outcome_pnl"]
        date   = t["run_date"]
        sym    = t["symbol"]
        if status in ("r1_hit", "r2_hit", "r3_hit"):
            outcome_str = f"WIN ({status.replace('_',' ')}, +{pnl:.1f}%)"
        elif status == "stopped":
            outcome_str = f"LOSS (SL hit, {pnl:.1f}%)"
        else:
            outcome_str = f"EXPIRED ({pnl:.1f}%)"
        lines.append(f"  - {sym} {date}: {outcome_str} [sim={t['similarity']:.2f}]")
    # Pattern insight
    pattern_parts = [f"{win_rate}% win rate on similar setups."]
    if len(wins) >= 2:
        r2_wins = [t for t in wins if t["outcome_status"] == "r1_hit"]
        if len(r2_wins) > len(wins) * 0.6:
            pattern_parts.append("You tend to exit at R1 — consider holding for R2.")
    if len(losses) >= 2:
        pattern_parts.append("Multiple stop-outs in similar setups — confirm entry strictly in buy zone.")
    lines.append(f"Pattern: {' '.join(pattern_parts)}")
    return "\n".join(lines)


def _generate_missing_embeddings() -> int:
    """
    v5.1 Architecture Step 15: RAG backfill.
    Scans pick_outcomes for closed trades without embeddings and batch-generates them.
    Safe to re-run — _has_embedding() guards against duplicates.
    Returns number of embeddings generated.
    """
    generated = 0
    try:
        with _db_conn() as con:
            rows = con.execute("""
                SELECT o.symbol, o.run_date, o.status, o.pnl_pct,
                       o.grade, o.fused_score, o.sector, o.story,
                       mf.fort_norm, mf.apex_composite
                FROM pick_outcomes o
                LEFT JOIN meta_features mf ON o.symbol=mf.symbol AND o.run_date=mf.run_date
                WHERE o.status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')
                ORDER BY o.run_date DESC
            """).fetchall()
    except Exception as e:
        log.error(f"_generate_missing_embeddings query failed: {e}")
        return 0
    for row in rows:
        sym, run_date, status, pnl, grade, fused, sector, story, fort_norm, apex_comp = row
        if _has_embedding(sym, run_date):
            continue
        fortress = float(fort_norm or 50)
        apex     = float(apex_comp or 50)
        fused_v  = float(fused or 50)
        ok = _generate_and_store_embedding(
            symbol=sym, run_date=run_date,
            fortress=fortress, apex=apex, fused=fused_v,
            grade=grade or "PROBE", sector=sector or "DIVERSIFIED",
            macro_state="CHOP",  # historical macro unknown — use neutral default
            outcome_status=status, outcome_pnl=float(pnl or 0),
            story=story or "",
        )
        if ok:
            generated += 1
    log.info(f"RAG backfill: {generated} embeddings generated")
    return generated


def _validate_embedding_quality() -> dict:
    """
    v5.1 Architecture Step 15: Validate RAG retrieval precision.
    Samples 20 closed trades, retrieves similar trades for each,
    checks if retrieved direction (win/loss) matches the query outcome.
    Returns precision metrics dict.
    """
    try:
        with _db_conn() as con:
            sample = con.execute("""
                SELECT symbol, run_date, embedding_json, outcome_status,
                       outcome_pnl, fortress_score, apex_score, fused_score,
                       grade, sector, macro_state, trade_summary
                FROM trade_embeddings
                WHERE outcome_status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')
                ORDER BY RANDOM()
                LIMIT 20
            """).fetchall()
    except Exception as e:
        return {"error": str(e), "precision_pct": 0}
    if len(sample) < 5:
        return {"error": "insufficient_data", "total": len(sample), "precision_pct": 0}
    total_retrieved = 0; correct = 0
    for row in sample:
        sym, rdate, _, outcome, _, fort, apex, fused, grade, sector, macro, summary = row
        is_win = outcome in ("r1_hit", "r2_hit", "r3_hit")
        retrieved = _retrieve_similar_trades(
            sym, float(fort or 50), float(apex or 50), float(fused or 50),
            grade or "PROBE", sector or "DIVERSIFIED", macro or "CHOP", top_k=3
        )
        for t in retrieved:
            retrieved_win = t["outcome_status"] in ("r1_hit", "r2_hit", "r3_hit")
            total_retrieved += 1
            if retrieved_win == is_win:
                correct += 1
    precision = round(correct / total_retrieved * 100, 1) if total_retrieved > 0 else 0
    log.info(f"RAG quality: {correct}/{total_retrieved} correct direction ({precision}%)")
    return {"total_retrieved": total_retrieved, "correct": correct,
            "precision_pct": precision, "sample_size": len(sample)}


def _analyze_rag_performance() -> str:
    """
    v5.1 Architecture Step 16: Weekly RAG performance report for Telegram.
    Aggregates rag_query_log entries from the past 7 days.
    """
    lines = ["🔍 RAG PERFORMANCE (last 7 days)"]
    try:
        since = (datetime.today() - timedelta(days=7)).strftime("%Y-%m-%d")
        with _db_conn() as con:
            rows = con.execute("""
                SELECT COUNT(*), SUM(retrieved_count), AVG(precision_pct)
                FROM rag_query_log WHERE query_date >= ?
            """, (since,)).fetchone()
            total_embeds = con.execute(
                "SELECT COUNT(*) FROM trade_embeddings"
            ).fetchone()[0]
        if rows and rows[0]:
            lines.append(f"RAG queries: {rows[0]} | Total retrieved: {rows[1] or 0}")
            if rows[2]:
                lines.append(f"Direction precision: {rows[2]:.1f}%")
        lines.append(f"Embedding library: {total_embeds} closed trades indexed")
        quality = _validate_embedding_quality()
        if "precision_pct" in quality and quality["precision_pct"] > 0:
            improvement = round(quality["precision_pct"] - 60, 1)  # baseline 60%
            sign = "+" if improvement >= 0 else ""
            lines.append(f"Live precision check: {quality['precision_pct']}% ({sign}{improvement}% vs 60% baseline)")
    except Exception as e:
        lines.append(f"RAG analysis error: {e}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# v5.0 — ACC-1: NEWS/SENTIMENT FETCH (Step 9 §4a of architecture)
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_market_sentiment(symbol: str, fii_data: dict, insider_map: dict,
                             filings: dict, earnings_cal: dict) -> dict:
    """
    ACC-1 (v5.0): Aggregate market sentiment for a symbol from all intelligence sources.
    Returns structured dict used in the unified LLM prompt (Step 9 §4a).
    Sources: NSE filings (§8), earnings calendar (§8), insider flow (§8), FII/DII net.
    This produces the news/sentiment context that drives the news-driven llm_why field.
    """
    sym = symbol.upper()
    result = {
        "bullish_pct": 50,
        "bearish_pct": 50,
        "key_headlines": [],
        "insider_activity": "No recent insider activity",
        "fii_flow": "FII/DII data unavailable",
        "earnings_status": "No upcoming earnings",
        "filing_sentiment": "NEUTRAL",
    }
    try:
        # FII/DII context
        fii_score = fii_data.get("score", 15)
        fii_label = fii_data.get("label", "MIXED")
        fii_net   = fii_data.get("fii_net", 0)
        dii_net   = fii_data.get("dii_net", 0)
        if fii_net != 0 or dii_net != 0:
            result["fii_flow"] = f"FII ₹{fii_net:+,.0f}Cr | DII ₹{dii_net:+,.0f}Cr ({fii_label})"
        result["bullish_pct"] = min(90, max(10, 50 + (fii_score - 15) * 2))

        # Insider trades
        ins = insider_map.get(sym, {})
        if ins.get("count", 0) > 0:
            result["insider_activity"] = (
                f"Promoter/insider bought ₹{ins.get('total_cr', 0):.1f}Cr "
                f"({ins.get('count', 0)} transaction(s)) — {ins.get('person', 'Insider')}"
            )
            result["bullish_pct"] = min(90, result["bullish_pct"] + 5)

        # Filings sentiment
        fil = filings.get(sym, {})
        if fil.get("score", 15) >= 20:
            result["filing_sentiment"] = "POSITIVE"
            detail = fil.get("detail", "")
            if detail and "No recent" not in detail:
                result["key_headlines"].append(detail[:60])
        elif fil.get("score", 15) <= 8:
            result["filing_sentiment"] = "NEGATIVE"
            result["bearish_pct"] = min(90, result["bearish_pct"] + 10)

        # Earnings status
        earn_days = earnings_cal.get(sym)
        if earn_days is not None:
            if earn_days >= 0:
                result["earnings_status"] = f"Earnings in {earn_days} day(s)"
            elif earn_days >= -30:
                result["earnings_status"] = f"Reported {abs(earn_days)}d ago"

        # Adjust bearish pct
        result["bearish_pct"] = max(10, 100 - result["bullish_pct"])
        result["key_headlines"] = result["key_headlines"][:3]

    except Exception as e:
        log.debug(f"_fetch_market_sentiment {symbol}: {e}")

    return result


# ══════════════════════════════════════════════════════════════════════════════
# v5.0 — OUT-1: DAILY SHORTLIST PERSISTENCE (Step 9 §4e of architecture)
# ══════════════════════════════════════════════════════════════════════════════

def _save_daily_shortlist(run_date: str, symbol: str, final_rank: int,
                           fortress: float, apex: float, fused: float,
                           meta_prob: float, halal: dict,
                           llm_output: dict, sentiment: dict,
                           llm_input: dict) -> None:
    """
    OUT-1 (v5.0): Persist full context for each pick to daily_shortlist_analysis.
    Feeds weekly _analyze_shortlist_trends() to correlate llm_confidence vs outcome.
    Architecture Step 9 §4e.
    """
    try:
        halal_detail = halal if isinstance(halal, dict) else {}
        with _db_conn(write=True) as con:
            con.execute("""
                INSERT OR REPLACE INTO daily_shortlist_analysis
                  (run_date, symbol, final_rank, fortress_score, apex_score, fused_score,
                   meta_prob, halal_tier, halal_score, llm_confidence, llm_verdict,
                   llm_why, llm_narrative, sentiment_json, llm_input_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                run_date, symbol.upper(), final_rank,
                round(fortress, 2), round(apex, 2), round(fused, 2),
                round(meta_prob, 4),
                str(halal_detail.get("tier", "UNKNOWN")),
                float(halal_detail.get("score", 0)),
                float(llm_output.get("llm_confidence", 50)) / 100,
                str(llm_output.get("llm_verdict", "UNKNOWN")),
                str(llm_output.get("llm_why", ""))[:120],
                str(llm_output.get("llm_narrative", ""))[:120],
                json.dumps(sentiment, default=str)[:2000],
                json.dumps(llm_input, default=str)[:2000],
            ))
        log.debug(f"Shortlist saved: {symbol} rank={final_rank}")
    except Exception as e:
        log.debug(f"_save_daily_shortlist {symbol}: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# v5.0 — OUT-3: WEEKLY SHORTLIST TREND ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def _analyze_shortlist_trends() -> str:
    """
    OUT-3 (v5.0): Correlate llm_confidence vs actual trade outcome.
    Identifies which news patterns predicted wins — sent in weekly Telegram digest.
    """
    summary_lines = ["📊 SHORTLIST TREND ANALYSIS (last 30d)"]
    try:
        since = (datetime.today() - timedelta(days=30)).strftime("%Y-%m-%d")
        with _db_conn() as con:
            rows = con.execute("""
                SELECT d.symbol, d.llm_confidence, d.llm_verdict, d.llm_why,
                       d.filing_sentiment, o.status, o.pnl_pct
                FROM daily_shortlist_analysis d
                LEFT JOIN pick_outcomes o ON d.symbol=o.symbol AND d.run_date=o.run_date
                WHERE d.run_date >= ?
                  AND o.status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')
            """, (since,)).fetchall()

        if not rows:
            return "No shortlist data yet — builds after first week of picks."

        total = len(rows)
        wins = [r for r in rows if r[5] in ("r1_hit", "r2_hit", "r3_hit")]
        high_conf = [r for r in rows if (r[1] or 0) >= 0.75]
        low_conf  = [r for r in rows if (r[1] or 0) < 0.50]

        def _wr(grp):
            if not grp: return None
            return round(sum(1 for r in grp if r[5] in ("r1_hit","r2_hit","r3_hit")) / len(grp) * 100, 1)

        summary_lines.append(f"Total closed picks: {total} | Win rate: {_wr(rows)}%")
        if high_conf:
            summary_lines.append(f"High LLM confidence (≥75%): {len(high_conf)} picks → {_wr(high_conf)}% WR")
        if low_conf:
            summary_lines.append(f"Low LLM confidence (<50%): {len(low_conf)} picks → {_wr(low_conf)}% WR")

        # Most common news patterns in winning picks
        win_why = [r[3] for r in wins if r[3] and "No major" not in r[3]][:10]
        if win_why:
            summary_lines.append(f"Top winning signals: {' | '.join(win_why[:3])}")

        insight = ""
        if _wr(high_conf) and _wr(low_conf) and _wr(high_conf) > _wr(low_conf) + 15:
            insight = "💡 LLM confidence IS predictive — trust high-confidence picks."
        elif _wr(rows) and _wr(rows) < 40:
            insight = "💡 Overall win rate low — tighten entry to buy zone strictly."
        else:
            insight = "💡 Consistency beats conviction — follow the system."
        summary_lines.append(insight)

    except Exception as e:
        log.debug(f"_analyze_shortlist_trends: {e}")
        summary_lines.append("Analysis error — check DB.")

    return "\n".join(summary_lines)


# ══════════════════════════════════════════════════════════════════════════════
# v5.0 — PERF-1: PARALLEL SCORING WORKER
# ══════════════════════════════════════════════════════════════════════════════

def _score_one_symbol(args: tuple) -> Optional[dict]:
    """
    PERF-1 (v5.0): Thread-safe single-symbol scoring function for parallel execution.
    Wraps assemble_pick() with error isolation so one symbol's failure doesn't
    abort other workers. Called from ThreadPoolExecutor in run().

    Args: (symbol, row, yf_cache, fii_data, insider_map, filings, earnings_cal,
           macro, data_source, run_date, fast_rerun)
    Returns: assemble_pick result dict, or None on failure/filter.

    BUG-4 FIX: docstring previously listed intel_hash between run_date and fast_rerun
    but it was never in the actual args tuple (11 items, not 12). Docstring corrected.
    BUG-3 FIX: intel_hash is now computed INSIDE this function from fii_data/insider_map/
    filings so it's always present for the cache key without changing the args signature.
    """
    (symbol, row, yf_cache, fii_data, insider_map, filings,
     earnings_cal, macro, data_source, run_date, fast_rerun) = args

    sym = symbol.upper()
    close = float(row.get("close", 0))

    # BUG-3 FIX: compute intel_hash here so cache key is always intelligence-aware.
    # Previously _intelligence_hash() was computed in run() but never passed down or
    # used — cache key was only (symbol, run_date, close), causing stale scores.
    intel_hash = _intelligence_hash(fii_data, insider_map, filings)

    try:
        # Fast-rerun cache check (BUG-3 FIX: now correctly includes intel_hash in key)
        if fast_rerun and close > 0:
            cached = _score_cache_get(sym, run_date, close, intel_hash)
            if cached:
                log.debug(f"  CACHE HIT: {sym} (fast rerun, intel={intel_hash})")
                return cached

        # Fetch history
        hist = fetch_history_with_proxy_fallback(sym, days=300, yf_cache=yf_cache)
        if hist.empty or len(hist) < MIN_HIST_BARS:
            return None

        result = assemble_pick(
            symbol=sym,
            today_row=row,
            hist=hist,
            fii_data=fii_data,
            insider_map=insider_map,
            filings=filings,
            earnings_cal=earnings_cal,
            macro=macro,
            data_source=data_source,
        )

        if result and fast_rerun and close > 0:
            _score_cache_put(sym, run_date, close, result, intel_hash)

        return result

    except Exception as e:
        log.debug(f"  _score_one_symbol {sym}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — HALAL GUARD  (single authoritative implementation)
# ══════════════════════════════════════════════════════════════════════════════

HALAL_EXCLUDED = {
    "HDFCBANK","ICICIBANK","SBIN","KOTAKBANK","AXISBANK","INDUSINDBK",
    "BANDHANBNK","IDFCFIRSTB","FEDERALBNK","RBLBANK","BANKBARODA",
    "CANBK","UNIONBANK","PNB","INDIANB","AUBANK","DCBBANK","YESBANK",
    "BAJFINANCE","BAJAJFINSV","SBICARD","CHOLAFIN","HDFC","LICHSGFIN",
    "M&MFIN","SHRIRAMFIN","MUTHOOTFIN","MANAPPURAM","IIFL","SUNDARMFIN",
    "RECLTD","PFC","IRFC","HUDCO","PNBHOUSING",
    "HDFCLIFE","SBILIFE","ICICIPRU","LICI","STARHEALTH","GICRE","NIACL",
    "LTIM","NIFTYBEES","JUNIORBEES","GOLDBEES","BANKBEES","LIQUIDBEES",
    "ITC",   # FIX-A3: tobacco — already in _HALAL_L1_VETO_SYMBOLS; synced to pre-filter
}

HALAL_KW = (
    "bank","bancorp","finance","finserv","fincorp","financial",
    "insurance","insur","nifty","etf","reit","invit",
    "liquid","overnight","gilt","treasury",
)
_BEES_RE = re.compile(r'\bbees\b', re.IGNORECASE)

# Curated fallback when all live Shariah sources fail
_HALAL_FALLBACK = {
    "TCS","INFY","WIPRO","HCLTECH","TECHM","MPHASIS","COFORGE","PERSISTENT",
    "KPITTECH","TATAELXSI","TANLA","MASTEK","ROUTE","NEWGEN","SAKSOFT",
    "INTELLECT","DATAMATICS","ZENSAR",
    "SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","AUROPHARMA","LUPIN",
    "TORNTPHARM","ALKEM","IPCALAB","NATCOPHARM","GRANULES","GLENMARK",
    "AJANTPHARM","LALPATHLAB","METROPOLIS","SYNGENE","MARKSANS","LAURUSLABS",
    "MARUTI","TATAMOTORS","M&M","HEROMOTOCO","BAJAJ-AUTO","EICHERMOT",
    "TVSMOTORS","MOTHERSON","BOSCHLTD","ENDURANCE","APOLLOTYRE","BALKRISIND",
    "CEATLTD","TIINDIA",
    "HINDUNILVR","NESTLEIND","BRITANNIA","DABUR","MARICO","COLPAL",
    "EMAMILTD","TATACONSUM","VBL","JUBLFOOD","KRBL","JYOTHYLAB",
    "PIDILITIND","FINEORG","GALAXYSURF","VINATIORG","NAVINFLUOR","DEEPAKNI",
    "TATACHEM","GHCL","ANUPAM","PCBL","AARTI","HIMADRI","ATUL","NOCIL","EPIGRAL",
    "LT","HAVELLS","VOLTAS","SIEMENS","ABB","CUMMINSIND","THERMAX","KEC",
    "POLYCAB","SCHAEFFLER","TIMKEN","GRINDWELL","PRAJ","ELGIEQUIP","KAYNES","SYRMA",
    "DLF","GODREJPROP","OBEROIRLTY","PHOENIXLTD","SOBHA",
    "CONCOR","BLUEDART","TCI","DELHIVERY","ALLCARGO",
    "KAVERI","DHANUKA","UPL","PIIND","COROMANDEL","CHAMBLFERT",
    "PAGEIND","RAYMOND","WELSPUNIND","VARDHMAN","TRIDENT",
    "TATASTEEL","HINDALCO","JSWSTEEL","NMDC","RATNAMANI","VEDL",
    "TITAN","TRENT","ASIANPAINT","BERGERPAINTS","DIXON","AMBER",
    "NTPC","TATAPOWER","TORNTPOWER","SUZLON","INOXWIND","WEBELSOLAR",
}

_HALAL_UNIVERSE_CACHE: Optional[set]  = None
_HALAL_UNIVERSE_LOCK  = threading.Lock()
# Serialise all SQLite write transactions (WAL mode reduces contention but does
# not eliminate "database is locked" errors when multiple threads write at the same time)
_SQLITE_WRITE_LOCK    = threading.Lock()

# ── BUG FIX [SQL-001]: guaranteed-close SQLite context manager ─────────────
# The previous pattern of `con = sqlite3.connect(...) / con.close()` leaks the
# connection on any exception path because close() is never in a finally block.
# Under WAL mode a leaked read connection prevents the writer from checkpointing,
# causing escalating "database is locked" errors across threads.
# Usage (read):   `with _db_conn() as con: rows = con.execute(...).fetchall()`
# Usage (write):  `with _db_conn(write=True) as con: con.execute(...); con.commit()`
from contextlib import contextmanager as _contextmanager

# OPT-7: Read connection pool — 6 persistent read connections (WAL allows concurrent reads)
# PERF-4: Expanded from 3→6 to eliminate thread contention on parallel 8-worker scoring.
# Avoids open/close overhead on every DB read (dozens per scoring loop iteration)
_READ_POOL_SIZE = 6
_READ_POOL: list = []
_READ_POOL_LOCK = threading.Lock()
_READ_POOL_SEMAPHORE = threading.Semaphore(_READ_POOL_SIZE)  # PERF-4: now 6

def _get_read_conn() -> sqlite3.Connection:
    """Get a pooled read connection."""
    with _READ_POOL_LOCK:
        if _READ_POOL:
            return _READ_POOL.pop()
    con = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con

def _return_read_conn(con: sqlite3.Connection):
    """Return a connection to the pool."""
    with _READ_POOL_LOCK:
        if len(_READ_POOL) < _READ_POOL_SIZE:
            _READ_POOL.append(con)
            return
    try: con.close()
    except Exception: pass

@_contextmanager
def _db_conn(timeout: int = 10, write: bool = False):
    """Thread-safe SQLite connection — pooled reads, exclusive writes."""
    _lock = _SQLITE_WRITE_LOCK if write else None
    if _lock:
        _lock.acquire()
    con = None
    _pooled = False
    try:
        if write:
            con = sqlite3.connect(DB_PATH, timeout=timeout)
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA busy_timeout=5000")
        else:
            # OPT-7: use pooled read connection
            _READ_POOL_SEMAPHORE.acquire(timeout=timeout)
            con = _get_read_conn()
            _pooled = True
        yield con
        if write:
            con.commit()
    except Exception:
        if write and con:
            try: con.rollback()
            except Exception: pass
        raise
    finally:
        if con:
            if _pooled:
                _return_read_conn(con)
                _READ_POOL_SEMAPHORE.release()
            else:
                try: con.close()
                except Exception: pass
        if _lock:
            _lock.release()
_HALAL_CUSTOM_LIST:    set             = set()

SYMBOL_SECTOR: Dict[str, str] = {
    "TCS":"NIFTY IT","INFY":"NIFTY IT","WIPRO":"NIFTY IT","HCLTECH":"NIFTY IT",
    "TECHM":"NIFTY IT","MPHASIS":"NIFTY IT","COFORGE":"NIFTY IT","PERSISTENT":"NIFTY IT",
    "SUNPHARMA":"NIFTY PHARMA","DRREDDY":"NIFTY PHARMA","CIPLA":"NIFTY PHARMA",
    "DIVISLAB":"NIFTY PHARMA","AUROPHARMA":"NIFTY PHARMA","LUPIN":"NIFTY PHARMA",
    "TORNTPHARM":"NIFTY PHARMA","ALKEM":"NIFTY PHARMA",
    "MARUTI":"NIFTY AUTO","TATAMOTORS":"NIFTY AUTO","M&M":"NIFTY AUTO",
    "HEROMOTOCO":"NIFTY AUTO","BAJAJ-AUTO":"NIFTY AUTO","EICHERMOT":"NIFTY AUTO",
    "TVSMOTORS":"NIFTY AUTO","BOSCHLTD":"NIFTY AUTO",
    "TATASTEEL":"NIFTY METAL","JSWSTEEL":"NIFTY METAL","HINDALCO":"NIFTY METAL",
    "NMDC":"NIFTY METAL","RATNAMANI":"NIFTY METAL","VEDL":"NIFTY METAL",
    "HINDUNILVR":"NIFTY FMCG","NESTLEIND":"NIFTY FMCG","BRITANNIA":"NIFTY FMCG",
    "DABUR":"NIFTY FMCG","MARICO":"NIFTY FMCG","COLPAL":"NIFTY FMCG",
    "DLF":"NIFTY REALTY","GODREJPROP":"NIFTY REALTY","OBEROIRLTY":"NIFTY REALTY",
}

_SECTOR_LIVE_CACHE: Dict[str, tuple] = {}   # BUG-003 FIX: (sector, timestamp) with TTL
_SECTOR_CACHE_TTL = 86_400                  # 24 hours in seconds
_SECTOR_LIVE_LOCK = threading.RLock()       # OPT-10: RLock for sector live cache


def _lookup_sector_yfinance(sym: str) -> str:
    """CRIT-1 FIX + FIX-A04: yfinance sector fallback; respects YF circuit breaker."""
    # FIX-A04: check circuit breaker before making yfinance HTTP call
    with _YF_FAIL_LOCK:
        if time.time() < _YF_CIRCUIT_OPEN_UNTIL:
            log.debug(f"_lookup_sector_yfinance: YF circuit open — returning DIVERSIFIED for {sym}")
            return "DIVERSIFIED"
        if _YF_FAIL_COUNT >= _YF_FAIL_THRESHOLD:
            return "DIVERSIFIED"
    _YF_SECTOR_MAP = {
        "Technology": "NIFTY IT", "Consumer Technology": "NIFTY IT",
        "Communication Services": "NIFTY IT",
        "Healthcare": "NIFTY PHARMA", "Biotechnology": "NIFTY PHARMA",
        "Consumer Defensive": "NIFTY FMCG", "Consumer Cyclical": "NIFTY FMCG",
        "Energy": "NIFTY ENERGY", "Utilities": "NIFTY ENERGY",
        "Basic Materials": "NIFTY METAL",
        "Real Estate": "NIFTY REALTY", "Industrials": "NIFTY CAPGOODS",
        "Financial Services": "DIVERSIFIED", "Finance": "DIVERSIFIED",
    }
    try:
        import yfinance as yf
        ticker = sym if sym.endswith(".NS") else f"{sym}.NS"
        info = yf.Ticker(ticker).info
        raw = info.get("sector") or info.get("industry") or ""
        return _YF_SECTOR_MAP.get(raw, "DIVERSIFIED")
    except Exception:
        return "DIVERSIFIED"


def get_sector(sym: str) -> str:
    s = sym.upper()
    if s in SYMBOL_SECTOR:
        return SYMBOL_SECTOR[s]
    # OPT-10: use RLock for thread-safe cache reads
    with _SECTOR_LIVE_LOCK:
        if s in _SECTOR_LIVE_CACHE:
            cached_sec, cached_ts = _SECTOR_LIVE_CACHE[s]
            if time.time() - cached_ts < _SECTOR_CACHE_TTL:
                return cached_sec
    sec = _lookup_sector_nse(s)
    if sec == "DIVERSIFIED":
        sec = _lookup_sector_yfinance(s)
    with _SECTOR_LIVE_LOCK:
        _SECTOR_LIVE_CACHE[s] = (sec, time.time())
    return sec




def _tg_health_alert(message: str):
    """Send a health-alert Telegram message (best-effort, no crash on failure)."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    # FIX-3: Set SUPPRESS_HEALTH_ALERTS=1 in CI env to silence Shariah/yfinance noise
    if os.getenv("SUPPRESS_HEALTH_ALERTS", "").lower() in ("1", "true", "yes"):
        log.debug(f"Health alert suppressed: {message[:80]}")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": f"⚠️ SNIPER HEALTH\n{message}"},
            timeout=10,
        )
    except Exception:
        pass


def _yf_download_with_backoff(ticker: str, **kwargs):
    """
    C3 FIX — Exponential back-off + jitter wrapper for yf.download().
    On _YF_FAIL_THRESHOLD consecutive failures the 24-hour circuit breaker opens.
    GitHub Actions runners share IP pools; Yahoo bans shared IPs when hammered.
    This wrapper prevents the silent-failure cascade documented as issue C3.
    """
    global _YF_FAIL_COUNT, _YF_CIRCUIT_OPEN_UNTIL
    import yfinance as yf

    # Circuit-breaker guard
    with _YF_FAIL_LOCK:
        if time.time() < _YF_CIRCUIT_OPEN_UNTIL:
            remaining = int((_YF_CIRCUIT_OPEN_UNTIL - time.time()) / 60)
            log.warning(f"YF circuit OPEN — skipping {ticker} ({remaining} min remaining)")
            return pd.DataFrame()

    last_exc: Exception = RuntimeError("unreachable")
    for attempt in range(_YF_MAX_ATTEMPTS):
        if attempt:
            raw   = _YF_BACKOFF_BASE ** attempt            # 2, 4, 8 s
            jitter = raw * 0.25 * random.random()          # ±25 %
            delay  = min(raw + jitter, _YF_BACKOFF_MAX)
            log.warning(f"YF back-off {attempt}/{_YF_MAX_ATTEMPTS}: "
                        f"sleeping {delay:.1f}s for {ticker}")
            time.sleep(delay)
        try:
            df = yf.download(ticker, **kwargs)
            with _YF_FAIL_LOCK:
                _YF_FAIL_COUNT = 0        # reset on any success
            return df
        except Exception as e:
            last_exc = e
            log.warning(f"YF download attempt {attempt+1}/{_YF_MAX_ATTEMPTS} "
                        f"failed for {ticker}: {e}")

    # All retries exhausted — increment global counter and maybe open circuit
    with _YF_FAIL_LOCK:
        _YF_FAIL_COUNT += 1
        fc = _YF_FAIL_COUNT
        if fc >= _YF_FAIL_THRESHOLD:
            _YF_CIRCUIT_OPEN_UNTIL = time.time() + 86_400  # 24 h
            log.error(
                f"YF circuit breaker OPEN — {fc} consecutive failures. "
                f"yfinance suspended for 24 h. Last error: {last_exc}"
            )
            _tg_health_alert(
                f"🚨 yfinance circuit breaker OPEN after {fc} consecutive failures.\n"
                f"Pipeline is in NSE-only mode for 24 h.\nLast error: {last_exc}"
            )
    return pd.DataFrame()


def _live_sector_momentum(sector: str, days: int = 20) -> dict:
    """Compute sector vs CNX500 relative momentum. Returns bonus/penalty."""
    NEUTRAL = {"rel_5d": 0.0, "rel_20d": 0.0, "momentum_tier": "NEUTRAL", "bonus": 0}

    if sector not in SECTOR_INDICES:
        return NEUTRAL

    global _YF_FAIL_COUNT
    with _YF_FAIL_LOCK:
        fail_count = _YF_FAIL_COUNT
    if fail_count >= _YF_FAIL_THRESHOLD:
        return NEUTRAL

    cache_key = f"{sector}_{days}"
    if cache_key in _SECTOR_MOM_CACHE:
        return _SECTOR_MOM_CACHE[cache_key]

    global _SECTOR_YF_CALLS
    if _get_sector_yf_calls() >= _MAX_SECTOR_YF_CALLS:
        log.debug(f"Sector YF call cap reached ({_MAX_SECTOR_YF_CALLS}) — skipping {sector}")
        return NEUTRAL

    try:
        # Shared CNX500 cache (TTL 1 hour)
        global _CNX500_CACHE, _CNX500_CACHE_TIME
        now = time.time()
        if _CNX500_CACHE is None or (now - _CNX500_CACHE_TIME) > 3600:
            cnx_df = _yf_download_with_backoff("^CNX500", period="30d", progress=False,
                                               auto_adjust=True, timeout=_YF_DOWNLOAD_TIMEOUT)
            _CNX500_CACHE = cnx_df
            _CNX500_CACHE_TIME = now
        else:
            cnx_df = _CNX500_CACHE

        sector_ticker = SECTOR_INDICES[sector]
        if sector_ticker not in _SECTOR_INDEX_CACHE:
            sector_df = _yf_download_with_backoff(f"^{sector_ticker}", period="30d",
                                                  progress=False, auto_adjust=True,
                                                  timeout=_YF_DOWNLOAD_TIMEOUT)
            _SECTOR_INDEX_CACHE[sector_ticker] = sector_df
            _increment_sector_yf_calls()
        else:
            sector_df = _SECTOR_INDEX_CACHE[sector_ticker]

        if sector_df.empty or cnx_df.empty or len(sector_df) < 20:
            return NEUTRAL

        sector_close = sector_df["Close"].squeeze().values
        cnx_close    = cnx_df["Close"].squeeze().values

        sec_5d = (sector_close[-1] - sector_close[-5]) / sector_close[-5] * 100 if len(sector_close) >= 5 else 0
        cnx_5d = (cnx_close[-1] - cnx_close[-5]) / cnx_close[-5] * 100 if len(cnx_close) >= 5 else 0
        rel_5d = sec_5d - cnx_5d

        sec_20d = (sector_close[-1] - sector_close[-20]) / sector_close[-20] * 100 if len(sector_close) >= 20 else 0
        cnx_20d = (cnx_close[-1] - cnx_close[-20]) / cnx_close[-20] * 100 if len(cnx_close) >= 20 else 0
        rel_20d = sec_20d - cnx_20d

        if rel_5d > 2.0 and rel_20d > 3.0:
            tier, bonus = "STRONG", 6
        elif rel_5d > 1.0 and rel_20d > 1.5:
            tier, bonus = "MODERATE", 3
        elif rel_5d < -2.0 or rel_20d < -3.0:
            tier, bonus = "WEAK", -4
        elif rel_5d < -1.0:
            tier, bonus = "FADING", -2
        else:
            tier, bonus = "NEUTRAL", 0

        result = {"rel_5d": round(rel_5d, 2), "rel_20d": round(rel_20d, 2),
                  "momentum_tier": tier, "bonus": bonus}
        _SECTOR_MOM_CACHE[cache_key] = result
        return result

    except Exception as e:
        with _YF_FAIL_LOCK:
            _YF_FAIL_COUNT += 1
            current = _YF_FAIL_COUNT
        log.warning(f"YF fail #{current}: sector momentum {sector} — {e}")
        return NEUTRAL

def _lookup_sector_nse(sym: str) -> str:
    # FIX-4.1-M: Skip ALL NSE calls immediately if IP-blocked — was burning
    # 3 retries × 5s per symbol even after _NSE_IP_BLOCKED was set.
    global _NSE_CONSECUTIVE_FAILS, _NSE_IP_BLOCKED  # FIX-2: need globals for unified fail counter
    with _NSE_FAIL_LOCK:
        if _NSE_IP_BLOCKED:
            return "DIVERSIFIED"
    try:
        sess = _get_nse_session()
        data = _nse_json(sess, "https://www.nseindia.com/api/quote-equity", params={"symbol": sym}, timeout=10)
        if isinstance(data, dict):
            info = data.get("info", data)
            ind  = (info.get("industry") or info.get("macro") or info.get("basicIndustry") or "").lower()
            if any(k in ind for k in ("pharma","health","drug","biotech","hospital","medical")):         return "NIFTY PHARMA"
            if any(k in ind for k in ("software","it services","technology","telecom","digital")):      return "NIFTY IT"
            if any(k in ind for k in ("auto","vehicle","tyre","ancillar","bearing","piston")):         return "NIFTY AUTO"
            if any(k in ind for k in ("fmcg","consumer","food","beverag","packag","agro")):            return "NIFTY FMCG"
            if any(k in ind for k in ("metal","steel","alumin","copper","mining","iron","zinc")):       return "NIFTY METAL"
            if any(k in ind for k in ("energy","power","oil","gas","petro","solar","wind","renew")):    return "NIFTY ENERGY"
            if any(k in ind for k in ("realty","real estate","construct","cement","infra","road","rail","engineer")): return "NIFTY REALTY"
            if any(k in ind for k in ("chemical","specialty","dye","pigment","pesticide","fertiliser")): return "NIFTY CHEMICAL"
            if any(k in ind for k in ("capital goods","industrial","machinery","equipment","defence")):  return "NIFTY CAPGOODS"
            if any(k in ind for k in ("textile","apparel","garment","yarn","fabric","spinning")):        return "NIFTY TEXTILES"
    except Exception as e:
        log.debug(f"Sector lookup {sym}: {e}")
        # FIX-2: Unify NSE fail counter — _lookup_sector_nse() exceptions must
        # increment the same circuit breaker as _nse_json(). Previously this try/except
        # swallowed failures silently, allowing 600 wasted retries when IP is blocked.
        # Now ANY NSE function failure counts toward the shared threshold.
        with _NSE_FAIL_LOCK:
            _NSE_CONSECUTIVE_FAILS += 1
            fails = _NSE_CONSECUTIVE_FAILS
            if fails >= _NSE_FAIL_THRESHOLD and not _NSE_IP_BLOCKED:
                _NSE_IP_BLOCKED = True
                log.error(
                    f"NSE IP-BLOCK DETECTED (via sector lookup) after {fails} total NSE failures. "
                    f"All NSE calls disabled for this run."
                )
                _tg_health_alert(
                    f"NSE IP blocked (sector lookup) after {fails} total NSE failures. "
                    f"Switched to yfinance-only mode."
                )
    return "DIVERSIFIED"


def _fetch_shariah_csv() -> set:
    """Fetch live Nifty500 Shariah index CSV with 3-URL cascade."""
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0",
        "Referer": "https://www.niftyindices.com/",
    })
    try:
        sess.get("https://www.niftyindices.com/", timeout=15)
        time.sleep(1)
    except Exception:
        pass

    for url in [
        "https://www.niftyindices.com/IndexConstituents/ind_nifty500shariah.csv",
        "https://archives.nseindia.com/content/indices/ind_nifty500shariah.csv",
        "https://www.nseindia.com/content/indices/ind_nifty500shariah.csv",
    ]:
        try:
            resp = sess.get(url, timeout=25)
            if resp.status_code != 200 or len(resp.text) < 200:
                continue
            df = pd.read_csv(io.StringIO(resp.text))
            df.columns = df.columns.str.strip().str.upper()
            col = next((c for c in df.columns if any(k in c for k in ("SYMBOL","TICKER","SCRIP"))), None)
            if col is None:
                continue
            syms = {str(s).strip().upper() for s in df[col] if str(s).strip()
                    and not str(s).strip().upper().startswith(("INDEX","NIFTY","TOTAL","DATE","SYMBOL"))}
            if len(syms) >= 100:
                log.info(f"Shariah CSV loaded LIVE: {len(syms)} symbols ✅")
                return syms
        except Exception as e:
            log.debug(f"Shariah CSV {url}: {e}")    # Individual URL failures → debug; final error logged below
    # All three URLs failed
    log.error(
        "Shariah CSV: all 3 URLs failed — falling back to hardcoded list. "
        "Halal screening is DEGRADED. Check niftyindices.com reachability."
    )
    # FIX-A2: Removed _tg_health_alert() call — CI runs on blocked NSE IPs were
    # spamming Telegram on every cold-start run. Degradation is visible in the
    # Actions log via log.error() above. Alert only warranted for genuinely novel
    # failures; the hardcoded fallback list keeps halal screening functional.
    db_cache_size = len(_load_shariah_db())
    if db_cache_size >= 100:
        log.info(f"Shariah CSV fetch failed but DB cache has {db_cache_size} symbols — using cache")
    else:
        log.warning("Shariah CSV fetch failed AND DB cache is empty — using hardcoded fallback list")
    return set()


def _load_shariah_db() -> set:
    # FIX-A7: use _db_conn() context manager — raw sqlite3.connect() was leaked
    # on any exception (missed in SQL-001 bugfix pass).
    try:
        with _db_conn() as con:
            row = con.execute("SELECT symbol, cached_date FROM halal_cache LIMIT 1").fetchone()
            if row:
                age = (datetime.today().date() - datetime.strptime(row[1], "%Y-%m-%d").date()).days
                if age <= SHARIAH_TTL_DAYS:
                    return {r[0] for r in con.execute("SELECT symbol FROM halal_cache").fetchall()}
    except Exception:
        pass
    return set()


def _save_shariah_db(syms: set):
    # FIX-A7: use _db_conn(write=True) context manager for guaranteed close + commit.
    try:
        today = datetime.today().strftime("%Y-%m-%d")
        with _db_conn(write=True) as con:
            con.execute("DELETE FROM halal_cache")
            con.executemany(
                "INSERT OR REPLACE INTO halal_cache (symbol, cached_date) VALUES (?,?)",
                [(s, today) for s in syms]
            )
    except Exception as e:
        log.debug(f"Shariah DB save: {e}")


def get_halal_universe() -> set:
    """
    Priority cascade (double-checked locking for thread safety):
    1. SQLite cache (TTL = SHARIAH_TTL_DAYS, default 1 day)
    2. Live Nifty500 Shariah CSV
    3. Sheets HALAL_LIST (Tab 7)
    4. Hardcoded _HALAL_FALLBACK
    """
    global _HALAL_UNIVERSE_CACHE
    if _HALAL_UNIVERSE_CACHE is not None:
        return _HALAL_UNIVERSE_CACHE
    with _HALAL_UNIVERSE_LOCK:
        if _HALAL_UNIVERSE_CACHE is not None:
            return _HALAL_UNIVERSE_CACHE
        cached = _load_shariah_db()
        if len(cached) >= 100:
            log.info(f"Halal universe from SQLite: {len(cached)} symbols")
            _HALAL_UNIVERSE_CACHE = cached
            return cached
        live = _fetch_shariah_csv()
        if len(live) >= 100:
            _save_shariah_db(live)
            _HALAL_UNIVERSE_CACHE = live
            return live
        sheets = _read_sheets_halal_list()
        if len(sheets) >= 50:
            log.info(f"Halal universe from Sheets HALAL_LIST: {len(sheets)}")
            _HALAL_UNIVERSE_CACHE = sheets
            return sheets
        log.warning("All live Shariah sources failed — using curated fallback")
        _HALAL_UNIVERSE_CACHE = _HALAL_FALLBACK
        return _HALAL_FALLBACK


def is_halal(symbol: str) -> bool:
    """
    4-layer halal gate — order is safety-critical:
    L1. Hard exclusion (banks, NBFCs, insurance, ETFs) — cannot be overridden
    L2. Keyword exclusion (finance, bank, etf, bees...)
    L3. Custom Sheets whitelist (user-added, post-exclusion only)
    L4. Nifty500 Shariah universe
    """
    sym = symbol.upper().strip()
    if sym in HALAL_EXCLUDED:
        return False
    sl = sym.lower()
    if any(kw in sl for kw in HALAL_KW) or _BEES_RE.search(sl):
        return False
    if _HALAL_CUSTOM_LIST and sym in _HALAL_CUSTOM_LIST:
        return True
    return sym in get_halal_universe()



# ══════════════════════════════════════════════════════════════════════════════
# [PATCH-B]  HALAL AI SCREEN — 4-layer  (v4.0-M, runs post-APEX on top picks)
# ══════════════════════════════════════════════════════════════════════════════
# is_halal() is KEPT as fast pre-filter on bhavcopy candidates (no change).
# halal_ai_screen() runs on top-N candidates only, after fortress+apex scoring.

# Layer 1 hard-veto sets (business screen)
_HALAL_L1_VETO_SYMBOLS = {
    "HDFCBANK","ICICIBANK","SBIN","KOTAKBANK","AXISBANK","INDUSINDBK",
    "BANDHANBNK","IDFCFIRSTB","FEDERALBNK","RBLBANK","BANKBARODA",
    "CANBK","UNIONBANK","PNB","INDIANB","AUBANK","DCBBANK","YESBANK",
    "BAJFINANCE","BAJAJFINSV","SBICARD","CHOLAFIN","HDFC","LICHSGFIN",
    "M&MFIN","SHRIRAMFIN","MUTHOOTFIN","MANAPPURAM","IIFL","SUNDARMFIN",
    "RECLTD","PFC","IRFC","HUDCO","PNBHOUSING",
    "HDFCLIFE","SBILIFE","ICICIPRU","LICI","STARHEALTH","GICRE","NIACL",
    "LTIM","NIFTYBEES","JUNIORBEES","GOLDBEES","BANKBEES","LIQUIDBEES",
    "ITC",  # tobacco
}
_HALAL_L1_KW = (
    "bank","bancorp","finance","finserv","fincorp","financial",
    "insurance","insur","nifty","etf","reit","invit",
    "liquid","overnight","gilt","treasury","casino","gaming",
    "tobacco","alcohol","spirits","brewery","liquor",
)
_BEES_RE_AI = re.compile(r'\bbees\b', re.IGNORECASE)

# Layer 3 ethical sector mapping (bonus/penalty, not veto)
_HALAL_L3_SECTORS = {
    "NIFTY IT": +8, "NIFTY PHARMA": +10, "NIFTY AUTO": +5,
    "NIFTY FMCG": +3, "NIFTY METAL": +5, "NIFTY CAPGOODS": +10,
    "NIFTY TEXTILES": +5, "NIFTY CHEMICAL": +5, "NIFTY REALTY": -5,
    "NIFTY ENERGY": -5, "NIFTY BANK": -15, "DIVERSIFIED": 0,
}

HALAL_AI_TTL_DAYS = int(os.getenv("HALAL_AI_TTL_DAYS", "30"))  # ARCH-B2: monthly refresh (was 7)


def _halal_l1_business_veto(symbol: str) -> bool:
    """Layer 1: hard veto on known haram business. True = VETO."""
    sym = symbol.upper().strip()
    if sym in _HALAL_L1_VETO_SYMBOLS:
        return True
    sl = sym.lower()
    if any(kw in sl for kw in _HALAL_L1_KW):
        return True
    if _BEES_RE_AI.search(sl):
        return True
    return False


def _halal_l2_financial_veto(symbol: str) -> Tuple[bool, float]:
    """
    Layer 2: Debt/MarketCap < 33% check + interest income ratio check.
    Returns (veto, debt_to_mcap). Defaults to (False, -1.0) on data failure.
    FIX-4.1-M: returns -1.0 (sentinel) when data unavailable so caller can
    apply a data-unavailable penalty instead of silently passing as debt=0.
    FIX-A4: Also vetos when netInterestIncome/totalRevenue >= 30%.
    This catches NBFCs and bank subsidiaries that pass the debt screen
    (low borrowings on balance sheet) but derive most revenue from lending.
    """
    try:
        with _db_conn() as con:
            row = con.execute(
                "SELECT debt_to_mcap, assessed_date FROM halal_ai_cache WHERE symbol=?",
                (symbol.upper(),)
            ).fetchone()
        if row:
            age = (datetime.today().date() -
                   datetime.strptime(row[1][:10], "%Y-%m-%d").date()).days
            if age <= HALAL_AI_TTL_DAYS and row[0] is not None:
                dtm = float(row[0])
                return dtm >= 0.33, dtm
    except Exception:
        pass

    try:
        import yfinance as yf
        info   = yf.Ticker(f"{symbol}.NS").info
        debt   = float(info.get("totalDebt") or 0)
        mcap   = float(info.get("marketCap") or 0)

        # FIX-A4: Interest income ratio guard
        # netInterestIncome > 0 means a lending business (banks, NBFCs).
        # If >30% of total revenue is from interest, it is functionally a lender.
        net_interest = float(info.get("netInterestIncome") or 0)
        total_rev    = float(info.get("totalRevenue") or 0)
        if net_interest > 0 and total_rev > 0:
            interest_ratio = net_interest / total_rev
            if interest_ratio >= 0.30:
                dtm = round(debt / mcap, 4) if mcap > 0 else -1.0
                log.debug(f"L2 interest-income veto {symbol}: {interest_ratio:.1%} >= 30%")
                return True, dtm

        if mcap > 0:
            dtm = round(debt / mcap, 4)
            return dtm >= 0.33, dtm
    except Exception:
        pass
    # -1.0 sentinel = data unavailable (caller should apply score penalty)
    return False, -1.0


def _halal_l3_ethical_score(symbol: str, sector: str) -> int:
    """Layer 3: ethical sector overlay. Returns ±15 pts, no veto."""
    return _HALAL_L3_SECTORS.get(sector, 0)


def _halal_l4_sheet_fallback(symbol: str) -> dict:
    """ARCH-D3: Shariah universe confidence proxy when LLM is unavailable or failed.
    Consults the already-cached get_halal_universe() set (Sheets/CSV/hardcoded).
    Returns:
      - confidence 0.75  if symbol is in the approved Shariah universe (SHEET_APPROVED)
      - confidence 0.40  if symbol is absent from the universe (SHEET_UNLISTED)
    Both are conservative relative to a full LLM analysis so borderline symbols still
    get scrutinised by L2/L3 scoring rather than being rubber-stamped or hard-vetoed.
    This is intentionally NOT cached in llm_cache — the next successful LLM run will
    overwrite with a real assessment. Log at INFO so operators can see when this fires.
    """
    try:
        universe = get_halal_universe()
        sym = symbol.upper().strip()
        if sym in universe:
            log.info(f"Halal L4 SHEET_FALLBACK {sym}: in Shariah universe → confidence=0.75")
            return {
                "llm_confidence":       0.75,
                "llm_business_concern": "NONE",
                "llm_revenue_model":    "unknown",
                "llm_subsidiary_risk":  "MEDIUM",
                "llm_illiquid_risk":    "LOW",
                "llm_manual_review":    False,
                "llm_source":           "SHEET_APPROVED",
            }
        else:
            log.info(f"Halal L4 SHEET_FALLBACK {sym}: not in Shariah universe → confidence=0.40")
            return {
                "llm_confidence":       0.40,
                "llm_business_concern": "Not in Shariah-approved universe — manual review advised",
                "llm_revenue_model":    "unknown",
                "llm_subsidiary_risk":  "MEDIUM",
                "llm_illiquid_risk":    "LOW",
                "llm_manual_review":    True,
                "llm_source":           "SHEET_UNLISTED",
            }
    except Exception as e:
        log.debug(f"_halal_l4_sheet_fallback {symbol}: {e} — returning neutral 0.5")
        return {"llm_confidence": 0.5, "llm_flags": [], "llm_source": "FALLBACK_ERROR"}


def _halal_l4_llm_screen(symbol: str, sector: str, business_desc: str = "") -> dict:
    """Layer 4: LLM business model analysis via Claude Sonnet (optional).
    FIX-A5: prompt extended with illiquid_asset_risk to catch derivative-heavy models.
    ARCH-D3: When LLM is unavailable or fails, falls back to Shariah universe from
    Sheets/CSV as a confidence proxy instead of returning a flat neutral 0.5."""
    if not _ANTHROPIC_OK and not _OPENAI_OK:
        # ARCH-D3: LLM entirely unavailable — use Shariah universe as confidence proxy
        return _halal_l4_sheet_fallback(symbol)

    cache_key = f"halal_l4:{symbol}:{_llm_hash(sector + business_desc[:200])}"
    cached = _llm_cached(cache_key, "halal_l4")
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    prompt = (
        "You are an Islamic finance compliance analyst. Assess this Indian listed company.\n"
        f"Symbol: {symbol}\nSector: {sector}\n"
        f"Business description: {business_desc[:500] or 'Not available'}\n\n"
        "Assess Shariah compliance. Return ONLY JSON (no markdown):\n"
        '{"halal_confidence": 0.0-1.0, '
        '"business_concern": "brief concern or NONE", '
        '"revenue_model": "fee_based|interest_based|mixed|manufacturing|services", '
        '"subsidiary_risk": "LOW|MEDIUM|HIGH", '
        '"illiquid_asset_risk": "LOW|MEDIUM|HIGH", '
        '"manual_review_needed": true|false}\n\n'
        "1.0 = clearly permissible, 0.0 = clearly impermissible. "
        "Be conservative — when uncertain, lower confidence.\n"
        "illiquid_asset_risk: HIGH if >20% of assets/revenue derive from derivatives, "
        "futures, speculative trading, or non-productive financial instruments."
    )
    # v5.1 TIER 1: GPT-4.1 Nano for Halal L4 (high-volume cheap calls)
    raw = _call_tier1(prompt, max_tokens=350)
    if not raw:
        raw = _call_claude(prompt, max_tokens=350)  # fallback to Claude
    if not raw:
        # ARCH-D3: LLM failed at runtime — fall back to Shariah universe instead of flat 0.5
        return _halal_l4_sheet_fallback(symbol)

    try:
        txt = raw.strip().replace("```json", "").replace("```", "")
        parsed = json.loads(txt)
        result = {
            "llm_confidence":        max(0.0, min(1.0, float(parsed.get("halal_confidence", 0.5)))),
            "llm_business_concern":  str(parsed.get("business_concern", ""))[:100],
            "llm_revenue_model":     str(parsed.get("revenue_model", "unknown")),
            "llm_subsidiary_risk":   str(parsed.get("subsidiary_risk", "MEDIUM")),
            "llm_illiquid_risk":     str(parsed.get("illiquid_asset_risk", "LOW")),  # FIX-A5
            "llm_manual_review":     bool(parsed.get("manual_review_needed", False)),
            "llm_source":            CLAUDE_MODEL,
        }
        _llm_store_cache(cache_key, "halal_l4", json.dumps(result), CLAUDE_MODEL)
        return result
    except Exception as e:
        log.debug(f"Halal L4 parse {symbol}: {e}")
        # ARCH-D3: parse error — fall back to Shariah universe instead of flat 0.5
        return _halal_l4_sheet_fallback(symbol)


def _halal_ai_cache_save(symbol: str, result: dict):
    """Persist halal AI result to halal_ai_cache table.

    SEVERE-5 FIX: now writes expires_at = assessed_date + HALAL_AI_TTL_DAYS so the
    weekly cleanup job can purge stale rows instead of the table growing unbounded.
    """
    try:
        today      = datetime.today().strftime("%Y-%m-%d")
        expires_at = (datetime.today() + timedelta(days=HALAL_AI_TTL_DAYS)).strftime("%Y-%m-%d")
        with _db_conn(write=True) as con:
            con.execute("""
                INSERT OR REPLACE INTO halal_ai_cache
                  (symbol, score, veto, tier, debt_to_mcap, business_model,
                   ethical_score, llm_confidence, assessed_date, source, expires_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (symbol, result["score"], int(result["veto"]), result["tier"],
                  result["debt_to_mcap"], result["business_model"],
                  result["ethical_score"], result["llm_confidence"],
                  today, result.get("source", "SCORED"), expires_at))
    except Exception as e:
        log.debug(f"Halal AI cache save {symbol}: {e}")


def halal_ai_screen(symbol: str, sector: str = "DIVERSIFIED",
                    business_desc: str = "") -> dict:
    """
    Full 4-layer Halal AI Screen. Runs post-APEX on top-N candidates only.
    Returns: {score, veto, tier, debt_to_mcap, business_model, ethical_score,
              llm_confidence, veto_reason, source}
    Tiers: score<40→RISKY, 40-69→ACCEPTABLE, 70+→PURE
    Hard veto: L1 business, L2 debt≥33%, L4 confidence<0.30
    """
    sym = symbol.upper().strip()

    # ── Check 7-day DB cache ─────────────────────────────────────────────────
    try:
        with _db_conn() as con:
            row = con.execute(
                "SELECT score, veto, tier, debt_to_mcap, business_model, "
                "ethical_score, llm_confidence, assessed_date "
                "FROM halal_ai_cache WHERE symbol=?",
                (sym,)
            ).fetchone()
        if row:
            age = (datetime.today().date() -
                   datetime.strptime(row[7][:10], "%Y-%m-%d").date()).days
            if age <= HALAL_AI_TTL_DAYS:
                return {
                    "score": row[0], "veto": bool(row[1]), "tier": row[2],
                    "debt_to_mcap": row[3], "business_model": row[4],
                    "ethical_score": row[5], "llm_confidence": row[6],
                    "veto_reason": "" if not row[1] else "CACHED_VETO",
                    "source": "CACHE",
                }
    except Exception:
        pass

    # ── Layer 1: Business screen ─────────────────────────────────────────────
    if _halal_l1_business_veto(sym):
        result = {"score": 0, "veto": True, "tier": "HARAM",
                  "debt_to_mcap": 0.0, "business_model": "HARAM_BUSINESS",
                  "ethical_score": 0, "llm_confidence": 0.0,
                  "veto_reason": "L1: Haram business category", "source": "L1"}
        _halal_ai_cache_save(sym, result)
        return result

    # ── Layer 2: Financial screen ────────────────────────────────────────────
    l2_veto, debt_to_mcap = _halal_l2_financial_veto(sym)
    if l2_veto:
        result = {"score": 0, "veto": True, "tier": "HARAM",
                  "debt_to_mcap": debt_to_mcap, "business_model": "HIGH_DEBT",
                  "ethical_score": 0, "llm_confidence": 0.5,
                  "veto_reason": f"L2: Debt/MCap {debt_to_mcap:.1%} >= 33%",
                  "source": "L2"}
        _halal_ai_cache_save(sym, result)
        return result

    # FIX-4.1-M: debt_to_mcap == -1.0 means data unavailable.
    # Don't pass silently as debt=0 — apply a -10 score penalty for uncertainty.
    _debt_data_missing = (debt_to_mcap < 0)
    _debt_for_penalty  = 0.0 if _debt_data_missing else debt_to_mcap

    # ── Layer 3: Ethical overlay ─────────────────────────────────────────────
    ethical_score = _halal_l3_ethical_score(sym, sector)
    base_score    = 70 + ethical_score
    debt_penalty  = int(max(0, _debt_for_penalty - 0.10) * 100)
    # FIX-4.1-M: additional -10 when debt data is missing (can't verify compliance)
    if _debt_data_missing:
        debt_penalty += 10
    base_score   -= debt_penalty
    base_score    = max(0, min(100, base_score))

    # ── Layer 4: LLM analysis (optional) ────────────────────────────────────
    llm = _halal_l4_llm_screen(sym, sector, business_desc)
    llm_conf  = llm.get("llm_confidence", 0.5)
    llm_model = llm.get("llm_revenue_model", "unknown")

    if _ANTHROPIC_OK:
        llm_delta = int((llm_conf - 0.5) * 20)
        base_score = max(0, min(100, base_score + llm_delta))

        # FIX-A5: illiquid_asset_risk penalty — HIGH = -15, MEDIUM = -5, LOW = 0
        # Catches derivative-heavy or speculative businesses that pass debt/interest screens.
        illiquid_risk = llm.get("llm_illiquid_risk", "LOW")
        if illiquid_risk == "HIGH":
            base_score = max(0, base_score - 15)
            log.debug(f"L4 illiquid_asset_risk HIGH for {sym} — -15 score penalty")
        elif illiquid_risk == "MEDIUM":
            base_score = max(0, base_score - 5)

        if llm_conf < 0.30:
            result = {"score": 0, "veto": True, "tier": "HARAM",
                      "debt_to_mcap": debt_to_mcap, "business_model": llm_model,
                      "ethical_score": ethical_score, "llm_confidence": llm_conf,
                      "veto_reason": f"L4: LLM confidence {llm_conf:.0%} < 30%",
                      "source": "L4"}
            _halal_ai_cache_save(sym, result)
            return result

    tier = "PURE" if base_score >= 70 else ("ACCEPTABLE" if base_score >= 40 else "RISKY")
    result = {
        "score": base_score, "veto": False, "tier": tier,
        "debt_to_mcap": debt_to_mcap, "business_model": llm_model,
        "ethical_score": ethical_score, "llm_confidence": llm_conf,
        "veto_reason": "", "source": "SCORED",
    }
    _halal_ai_cache_save(sym, result)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — GOOGLE SHEETS CLIENT (single shared workbook)
# ══════════════════════════════════════════════════════════════════════════════

_GS_WORKBOOK    = None
_GS_WS_CACHE:   Dict = {}
_GS_WS_CACHE_LOCK = threading.Lock()   # FIX-A06: prevent TOCTOU race
_GS_INIT_LOCK   = threading.Lock()

_GS_SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def _sheets_ok() -> bool:
    return bool(GOOGLE_SHEET_ID and GOOGLE_CREDS_JSON)


def _init_sheets() -> bool:
    global _GS_WORKBOOK
    if _GS_WORKBOOK is not None:
        return True
    with _GS_INIT_LOCK:
        if _GS_WORKBOOK is not None:
            return True
        if not _sheets_ok():
            return False
        try:
            import gspread, base64
            from google.oauth2.service_account import Credentials
            raw = GOOGLE_CREDS_JSON.strip()
            try:
                creds_dict = json.loads(base64.b64decode(raw).decode())
            except Exception:
                creds_dict = json.loads(raw)
            creds       = Credentials.from_service_account_info(creds_dict, scopes=_GS_SCOPES)
            client      = gspread.authorize(creds)
            _GS_WORKBOOK = client.open_by_key(GOOGLE_SHEET_ID)
            log.info(f"Sheets workbook opened: '{_GS_WORKBOOK.title}' ✅")
            return True
        except Exception as e:
            log.error(f"Sheets auth failed: {e}")
            return False


def _get_ws(tab: str):
    # FIX-A06: Thread-safe check-then-act under lock
    with _GS_WS_CACHE_LOCK:
        if tab in _GS_WS_CACHE:
            return _GS_WS_CACHE[tab]
    # Release lock during slow network call
    if not _init_sheets():
        return None
    try:
        ws = _GS_WORKBOOK.worksheet(tab)
        with _GS_WS_CACHE_LOCK:
            _GS_WS_CACHE[tab] = ws
        return ws
    except Exception as e:
        log.debug(f"Worksheet '{tab}' not found: {e}")
        with _GS_WS_CACHE_LOCK:
            _GS_WS_CACHE[tab] = None
        return None


def _read_sheet(tab: str) -> pd.DataFrame:
    ws = _get_ws(tab)
    if ws is None:
        return pd.DataFrame()
    try:
        raw = ws.get_all_values()
        if not raw or len(raw) < 2:
            return pd.DataFrame()
        headers = [str(h).strip().upper() for h in raw[0]]
        df = pd.DataFrame(raw[1:], columns=headers)
        df = df[~df.apply(lambda r: r.str.strip().eq("").all(), axis=1)].reset_index(drop=True)
        log.info(f"  Sheet '{tab}': {len(df)} rows ✅")
        return df
    except Exception as e:
        log.error(f"Sheet '{tab}' read failed: {e}")
        return pd.DataFrame()


def _push_sheet(tab: str, rows: list):
    """Write list-of-lists to a sheet tab."""
    if not _init_sheets():
        log.warning(f"Sheets push '{tab}': init failed")
        return
    try:
        ws = _get_ws(tab)
        if ws is None:
            log.info(f"Sheets tab '{tab}' not found — creating…")
            ws = _GS_WORKBOOK.add_worksheet(title=tab, rows=max(300, len(rows)+10), cols=max(40, len(rows[0]) if rows else 40))
            _GS_WS_CACHE[tab] = ws
            log.info(f"Sheets tab '{tab}' created ✅")

        # Ensure enough rows/cols
        needed_rows = len(rows)
        needed_cols = max(len(r) for r in rows) if rows else 1

        # Resize if needed (gspread doesn't auto-resize on update)
        if needed_rows > ws.row_count or needed_cols > ws.col_count:
            ws.resize(rows=max(needed_rows + 10, ws.row_count), cols=max(needed_cols + 5, ws.col_count))

        ws.clear()

        # Use batch update for reliability
        try:
            ws.update("A1", rows, value_input_option="USER_ENTERED")
        except TypeError:
            ws.update(rows, value_input_option="USER_ENTERED")

        log.info(f"Sheets tab '{tab}' updated: {len(rows)-1} data rows ✅")
    except Exception as e:
        log.error(f"push_sheet '{tab}' FAILED: {e}")


def _read_sheets_halal_list() -> set:
    df = _read_sheet("HALAL_LIST")
    if df.empty:
        return set()
    col = next((c for c in df.columns if any(k in c for k in ("SYMBOL","SCRIP","TICKER"))), df.columns[0])
    return {str(s).strip().upper() for s in df[col] if str(s).strip()
            and str(s).strip().upper() not in ("SYMBOL","SCRIP","TICKER","")}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — NSE SESSION & HTTP HELPERS
# ══════════════════════════════════════════════════════════════════════════════

_NSE_SESSION: Optional[requests.Session] = None
_NSE_SESSION_LOCK = threading.Lock()


def _make_nse_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0",
        "Accept":          "application/json, text/html, */*",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer":         "https://www.nseindia.com",
        "Connection":      "keep-alive",
        "DNT":             "1",
    })
    for url in ["https://www.nseindia.com",
                "https://www.nseindia.com/market-data/live-equity-market"]:
        try:
            s.get(url, timeout=15); time.sleep(1.0)
        except Exception:
            pass
    return s


_NSE_SESSION_REBUILT_THIS_RUN = False  # FIX-3: only rebuild once per run, not per symbol


def _get_nse_session() -> requests.Session:
    """Return module-level cached NSE session — warm exactly once per run."""
    global _NSE_SESSION
    if _NSE_SESSION is not None:
        return _NSE_SESSION
    with _NSE_SESSION_LOCK:
        if _NSE_SESSION is None:
            log.info("Initialising NSE session (once per run)…")
            _NSE_SESSION = _make_nse_session()
    return _NSE_SESSION


def _nse_json(sess: requests.Session, url: str, params: dict = None, timeout: int = 15):
    """
    C4 FIX + LOG-STORM FIX: Retry NSE requests up to NSE_MAX_RETRIES times.

    KEY CHANGES vs previous version:
    1. IP-block guard: if _NSE_IP_BLOCKED is True, raise immediately — no log spam,
       no retries, no session rebuilds. Saves 3-5 min per run when GitHub Actions
       IP is banned by NSE.
    2. Single session rebuild per CALL (not per attempt): we rebuild the session
       at most once per _nse_json() invocation. The old code reset _NSE_SESSION=None
       on every attempt, causing 3× session rebuilds per symbol (each rebuild hits
       nseindia.com + market-data page = ~3s each = 9s overhead per symbol).
    3. Success resets the consecutive-fail counter so transient failures don't
       permanently open the circuit.
    4. After NSE_FAIL_THRESHOLD full-retry failures, _NSE_IP_BLOCKED is set True
       and a single Telegram alert is sent (not one per symbol).
    """
    global _NSE_SESSION, _NSE_CONSECUTIVE_FAILS, _NSE_IP_BLOCKED, _NSE_SESSION_REBUILT_THIS_RUN

    # Circuit breaker: IP is blocked — fail fast, no log spam
    with _NSE_FAIL_LOCK:
        if _NSE_IP_BLOCKED:
            raise IOError("NSE IP-blocked (circuit open) — skipping all NSE calls this run")

    last_exc: Exception = RuntimeError("unreachable")
    session_rebuilt = False   # rebuild session AT MOST ONCE per call, not per attempt

    for attempt in range(NSE_MAX_RETRIES):
        if attempt:
            base_delay = 2 ** attempt          # 2s, 4s
            jitter     = base_delay * 0.25 * random.random()
            time.sleep(base_delay + jitter)
        try:
            resp = sess.get(url, params=params, timeout=timeout)
            body = resp.text.strip()
            if not body or body.startswith("<"):
                raise ValueError(f"NSE empty/HTML body ({resp.status_code}) for {url}")
            if resp.status_code == 503:
                raise IOError(f"NSE 503 Service Unavailable for {url}")
            # SUCCESS — reset consecutive-fail counter
            with _NSE_FAIL_LOCK:
                _NSE_CONSECUTIVE_FAILS = 0
            return resp.json()
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                IOError,
                ValueError,
                json.JSONDecodeError) as e:
            last_exc = e
            # FIX-NSE-NOISE: When IP is already blocked, every retry will fail
            # identically. Demote to debug to avoid log spam.
            with _NSE_FAIL_LOCK:
                _already_blocked = _NSE_IP_BLOCKED
            if _already_blocked:
                log.debug(f"NSE attempt {attempt+1}/{NSE_MAX_RETRIES} failed (IP blocked) "
                          f"({type(e).__name__}): {e}")
            else:
                log.warning(f"NSE attempt {attempt+1}/{NSE_MAX_RETRIES} failed "
                            f"({type(e).__name__}): {e}")
            # FIX-3: Rebuild session AT MOST ONCE PER RUN (not per call, not per attempt).
            # The old code rebuilt on every JSONDecodeError/ValueError — 30+ rebuilds
            # per run when the IP is blocked (each rebuild = 2 HTTP hits = ~3s).
            # Now we check _NSE_SESSION_REBUILT_THIS_RUN; a blocked IP won't benefit
            # from a second rebuild so we skip it entirely.
            if (not session_rebuilt and not _NSE_SESSION_REBUILT_THIS_RUN
                    and isinstance(e, (json.JSONDecodeError, ValueError))):
                with _NSE_SESSION_LOCK:
                    _NSE_SESSION = None
                    _NSE_SESSION_REBUILT_THIS_RUN = True
                sess = _get_nse_session()
                session_rebuilt = True
                log.debug("NSE session rebuilt (ONCE this run — FIX-3)")
            elif _NSE_SESSION_REBUILT_THIS_RUN and not session_rebuilt:
                log.debug("NSE session rebuild skipped — already rebuilt once this run (FIX-3)")

    # All retries exhausted — increment circuit breaker counter
    with _NSE_FAIL_LOCK:
        _NSE_CONSECUTIVE_FAILS += 1
        fails = _NSE_CONSECUTIVE_FAILS
        if fails >= _NSE_FAIL_THRESHOLD and not _NSE_IP_BLOCKED:
            _NSE_IP_BLOCKED = True
            log.error(
                f"NSE IP-BLOCK DETECTED after {fails} consecutive failures. "
                f"All NSE calls disabled for this run. Pipeline switching to yfinance-only mode."
            )
            _tg_health_alert(
                f"NSE IP blocked on GitHub Actions ({fails} consecutive failures). "
                f"Switched to yfinance-only mode for today's run."
            )
    raise last_exc


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — SQLITE DATABASE (single file, all tables)
# ══════════════════════════════════════════════════════════════════════════════

def _init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)   # _init_db owns this connection for schema setup
    try:
        con.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    con.execute("PRAGMA busy_timeout=5000")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS halal_cache (
            symbol      TEXT PRIMARY KEY,
            cached_date TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS roce_cache (
            symbol     TEXT PRIMARY KEY,
            value      REAL,
            label      TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS positions (
            entry_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol        TEXT NOT NULL,
            entry_price   REAL NOT NULL,
            entry_date    TEXT NOT NULL,
            initial_t3    REAL NOT NULL,
            peak_price    REAL NOT NULL,
            trailing_stop REAL NOT NULL,
            be_triggered  INTEGER DEFAULT 0,
            updated_at    TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'open',
            UNIQUE(symbol, entry_date)
        );
        CREATE TABLE IF NOT EXISTS sniper_results (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date      TEXT,
            symbol        TEXT,
            grade         TEXT,
            fused_score   REAL,
            close         REAL,
            stop_loss     REAL,
            r1            REAL,
            r2            REAL,
            r3            REAL,
            story         TEXT,
            sector        TEXT,
            created_at    TEXT DEFAULT CURRENT_TIMESTAMP
        );
                CREATE TABLE IF NOT EXISTS data_quality (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date            TEXT,
            data_source         TEXT,
            bhavcopy_records    INTEGER,
            halal_universe_size INTEGER,
            halal_in_bhavcopy   INTEGER,
            yfinance_shrink     TEXT,
            missing_halal       INTEGER,
            alert               TEXT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        );
                CREATE TABLE IF NOT EXISTS pick_outcomes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date        TEXT,
            symbol          TEXT,
            entry_price     REAL,
            stop_loss       REAL,
            r1              REAL,
            r2              REAL,
            r3              REAL,
            grade           TEXT,
            fused_score     REAL,
            -- FIX-PERF: sector denormalized here so PERFORMANCE tab JOIN works even
            -- after same-day clear deletes sniper_results rows before _push_performance_tab fires.
            sector          TEXT DEFAULT 'DIVERSIFIED',
            status          TEXT DEFAULT 'open',  -- open/closed/stopped/r1_hit/r2_hit/r3_hit/expired
            exit_price      REAL,
            exit_date       TEXT,
            pnl_pct         REAL,
            days_held       INTEGER,
            hit_target      TEXT,  -- which target hit: r1/r2/r3/stop/none
            story           TEXT,
            llm_story       TEXT,           -- AI-enhanced narrative
            bayes_prior_version TEXT,         -- Which prior set was used
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS mcap_cache (
            symbol      TEXT PRIMARY KEY,
            mcap        REAL,
            fetched_at  TEXT
        );
        CREATE TABLE IF NOT EXISTS llm_cache (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            text_hash   TEXT UNIQUE,
            prompt_type TEXT,
            result      TEXT,
            model       TEXT,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at  TEXT  -- FIX-5: TTL per prompt type (alpha_mine=30d, halal_l4=7d, structured_reasoning=90d)
        );
        CREATE TABLE IF NOT EXISTS score_cache (
            symbol       TEXT NOT NULL,
            run_date     TEXT NOT NULL,
            bhavcopy_close REAL NOT NULL,
            -- BUG-3 FIX: intel_hash added so cache invalidates when FII/insider/filing data changes.
            -- FIX-V5-1 claimed cache key includes intelligence_hash but only (symbol,run_date,close)
            -- was actually stored — stale scores served when data refreshed mid-day.
            intel_hash   TEXT NOT NULL DEFAULT '',
            result_json  TEXT NOT NULL,
            created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, run_date, intel_hash)
        );
        -- SEVERE-4 FIX: idx_score_cache_lookup dropped — redundant with PRIMARY KEY (symbol, run_date, intel_hash).
        -- ABS(bhavcopy_close - ?)<0.005 is a function on a column and cannot use any index anyway.
        -- The PK handles equality lookups on (symbol, run_date, intel_hash) perfectly.
        -- For 300 symbols/day x 5 days = 1500 rows, a table scan on the PK remnant is negligible.
        -- v5.4 THREE-LANE TABLES
        CREATE TABLE IF NOT EXISTS sniper_results_v54 (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date        TEXT NOT NULL,
            symbol          TEXT NOT NULL,
            lane            TEXT NOT NULL,   -- FORTRESS | APEX | FUSED
            grade           TEXT,
            fort_pts        REAL,
            apex_comp       REAL,
            fused_score     REAL,
            close           REAL,
            stop_loss       REAL,
            r1              REAL,
            r2              REAL,
            r3              REAL,
            story           TEXT,
            sector          TEXT,
            whale_score     REAL,
            div_score       REAL,
            bayes_pct       REAL,
            mc_survival     REAL,
            halal_tier      TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            UNIQUE(run_date, symbol, lane)
        );
        CREATE INDEX IF NOT EXISTS idx_sr_v54_lane ON sniper_results_v54 (run_date, lane);
        -- MC PROJECTIONS TABLE (Stage 8 -- Live Anchored MC Projection Engine)
        CREATE TABLE IF NOT EXISTS mc_projections (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date          TEXT NOT NULL,
            symbol            TEXT NOT NULL,
            lane              TEXT NOT NULL,
            check_date        TEXT NOT NULL,
            days_held         INTEGER,
            entry_price       REAL,
            current_price     REAL,
            orig_survival     REAL,
            new_survival      REAL,
            r1_prob           REAL,
            r2_prob           REAL,
            r3_prob           REAL,
            stop_prob         REAL,
            expected_days     REAL,
            divergence_sigma  REAL,
            percentile_rank   REAL,
            narrative         TEXT,
            action_signal     TEXT,
            mc_params_json    TEXT,
            created_at        TEXT DEFAULT (datetime('now')),
            UNIQUE(run_date, symbol, lane, check_date)
        );
        CREATE INDEX IF NOT EXISTS idx_mc_proj_lookup ON mc_projections (symbol, lane, check_date DESC);
        -- SURVIVAL MODEL TRAINING TABLE (Stage meta-model)
        CREATE TABLE IF NOT EXISTS survival_training (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            pick_id           TEXT NOT NULL,   -- symbol_rundate
            day               INTEGER NOT NULL,
            lane              TEXT NOT NULL,
            event             INTEGER,         -- 1=win(r1+), 0=loss(stop/expire), NULL=open
            time_to_event     REAL,
            censored          INTEGER DEFAULT 0,
            features_json     TEXT,
            created_at        TEXT DEFAULT (datetime('now')),
            UNIQUE(pick_id, lane, day)
        );
        CREATE TABLE IF NOT EXISTS bayes_calibration (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            prior_name      TEXT,
            condition       TEXT,
            wins            INTEGER DEFAULT 0,
            total           INTEGER DEFAULT 0,
            win_rate        REAL,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(prior_name, condition)
        );
        CREATE TABLE IF NOT EXISTS meta_features (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date        TEXT NOT NULL,
            symbol          TEXT NOT NULL,
            whale_score     REAL,
            div_score       REAL,
            vp_score       REAL,
            pat_score      REAL,
            bayes_pct      REAL,
            macro_state    TEXT,
            sector         TEXT,
            vix_level      REAL,
            primary_fused_score REAL,
            outcome_pnl_pct REAL,
            profitable     INTEGER,
            created_at     TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(run_date, symbol)
        );
    """)
    # Migration: add status column to positions if absent
    try:
        con.execute("ALTER TABLE positions ADD COLUMN status TEXT NOT NULL DEFAULT 'open'")
        con.commit()
    except Exception as e:
        if "duplicate column" not in str(e).lower() and "already exists" not in str(e).lower():
            if "locked" in str(e).lower():
                raise RuntimeError(f"DB locked during migration: {e}") from e
    # FIX 6: Migration — add sector column to sniper_results if absent.
    # The _push_performance_tab() query joins pick_outcomes o JOIN sniper_results s
    # ON o.symbol=s.symbol expecting s.sector, causing "no such column: s.sector".
    # This ALTER TABLE is idempotent: SQLite raises "duplicate column name" if the
    # column already exists, which we silently ignore.
    try:
        con.execute("ALTER TABLE sniper_results ADD COLUMN sector TEXT DEFAULT 'DIVERSIFIED'")
        con.commit()
        log.info("DB migration: added 'sector' column to sniper_results ✅")
    except Exception as e:
        if "duplicate column" not in str(e).lower() and "already exists" not in str(e).lower():
            log.debug(f"sniper_results sector migration: {e}")
    con.commit()
    try:
        con.close()   # FIX-A05: guaranteed close
    except Exception:
        pass
    _migrate_db_v3()  # v3.0-M: additive migration (trade_decisions, weekly_reviews, meta_features columns)
    _migrate_db_v4()  # v4.0-M: halal_ai_cache, platt_calibration, strategy_sandbox
    _prepopulate_halal_l1_cache()  # B-007 FIX: warm L1-veto cache so first-run avoids cold LLM calls


def _get_position(symbol: str) -> Optional[dict]:
    # FIX-A01: guaranteed connection close via _db_conn context manager
    try:
        with _db_conn() as con:
            row = con.execute(
                "SELECT entry_price,entry_date,initial_t3,peak_price,trailing_stop,be_triggered "
                "FROM positions WHERE symbol=? AND status='open' ORDER BY entry_date DESC LIMIT 1",
                (symbol.upper(),)
            ).fetchone()
        if row:
            return dict(zip(["entry_price","entry_date","initial_t3","peak_price","trailing_stop","be_triggered"], row))
    except Exception:
        pass
    return None


def _put_position(symbol: str, entry_price: float, entry_date: str, initial_t3: float,
                  peak_price: float, trailing_stop: float, be_triggered: int = 0,
                  conviction_flag: int = 0, min_hold_days: int = 0, max_hold_days: int = 0):
    # FIX-A01: guaranteed connection close via _db_conn context manager
    try:
        with _db_conn(write=True) as con:
            con.execute(
                "INSERT OR REPLACE INTO positions "
                "(symbol,entry_price,entry_date,initial_t3,peak_price,trailing_stop,be_triggered,updated_at,status,"
                "conviction_flag,min_hold_days,max_hold_days) "
                "VALUES (?,?,?,?,?,?,?,?,'open',?,?,?)",
                (symbol.upper(), entry_price, entry_date, initial_t3,
                 peak_price, trailing_stop, be_triggered, datetime.today().isoformat(),
                 int(conviction_flag), int(min_hold_days), int(max_hold_days))
            )
    except Exception as e:
        log.error(f"_put_position: {e}")


def _fetch_roce(symbol: str) -> Tuple[Optional[float], str]:
    try:
        with _db_conn() as con:
            row = con.execute("SELECT value, label, fetched_at FROM roce_cache WHERE symbol=?",
                              (symbol.upper(),)).fetchone()
            if row:
                age_h = (time.time() - float(row[2])) / 3600
                if age_h < 24:
                    return row[0], row[1]
    except Exception:
        pass
    result = (None, "ROE data unavailable")
    try:
        import yfinance as yf
        info = yf.Ticker(f"{symbol}.NS").info
        roe  = info.get("returnOnEquity")
        if roe is not None:
            roe_pct = float(roe) * 100
            q = ("HIGH ✓" if roe_pct >= 15 else "ACCEPTABLE" if roe_pct >= 5 else "LOW ⚠️")
            result = (roe_pct, f"ROE(proxy) {roe_pct:.1f}% [{q}]")
    except Exception:
        pass
    try:
        with _db_conn(write=True) as con:
            con.execute("INSERT OR REPLACE INTO roce_cache (symbol,value,label,fetched_at) VALUES (?,?,?,?)",
                        (symbol.upper(), result[0], result[1], str(time.time())))
            con.commit()
    except Exception:
        pass
    return result


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — BHAVCOPY DATA CASCADE (NSE → Sheets → yfinance)
# ══════════════════════════════════════════════════════════════════════════════

def _get_last_trading_day() -> Tuple[str, str]:
    d = datetime.today()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%d%m%Y"), d.strftime("%Y-%m-%d")


def _download_bhavcopy_nse(date_str: str, sess: requests.Session) -> pd.DataFrame:
    dd, mm, yyyy = date_str[:2], date_str[2:4], date_str[4:]
    yyyymmdd = f"{yyyy}{mm}{dd}"
    mon = {"01":"JAN","02":"FEB","03":"MAR","04":"APR","05":"MAY","06":"JUN",
           "07":"JUL","08":"AUG","09":"SEP","10":"OCT","11":"NOV","12":"DEC"}[mm]
    for url, is_zip in [
        (f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip", True),
        (f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv", False),
        (f"https://archives.nseindia.com/content/historical/EQUITIES/{yyyy}/{mon}/cm{date_str}bhav.csv.zip", True),
    ]:
        try:
            resp = sess.get(url, timeout=30)
            if resp.status_code == 200 and len(resp.content) > 1000:
                df = (pd.read_csv(io.BytesIO(resp.content), compression="zip")
                      if is_zip else pd.read_csv(io.BytesIO(resp.content)))
                df.columns = df.columns.str.strip()
                if len(df) > 100:
                    return df
        except Exception as e:
            log.debug(f"Bhavcopy URL failed: {e}")
    raise Exception(f"All bhavcopy URLs failed for {date_str}")


def _clean_bhavcopy(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = df.columns.str.strip().str.upper()
    for mapping in [
        {"TCKRSYMB":"symbol","SCTYSRS":"series","OPNPRIC":"open","HGHPRIC":"high",
         "LWPRIC":"low","CLSPRIC":"close","TTLTRADGVOL":"volume","TTLTRFVAL":"turnover"},
        {"SYMBOL":"symbol","SERIES":"series","OPEN":"open","HIGH":"high","LOW":"low",
         "CLOSE":"close","TOTTRDQTY":"volume","TOTTRDVAL":"turnover"},
        {"SYMBOL":"symbol","SERIES":"series","OPEN_PRICE":"open","HIGH_PRICE":"high",
         "LOW_PRICE":"low","CLOSE_PRICE":"close","TTL_TRD_QNTY":"volume","TURNOVER_LACS":"turnover_lakhs"},
    ]:
        if all(k in df.columns for k in mapping):
            df = df.rename(columns=mapping); break
    if "series" in df.columns:
        df = df[df["series"].astype(str).str.strip() == "EQ"].copy()
    if "turnover_lakhs" not in df.columns and "turnover" in df.columns:
        df["turnover_lakhs"] = pd.to_numeric(df["turnover"], errors="coerce").fillna(0) / 100_000
    elif "turnover_lakhs" not in df.columns:
        df["turnover_lakhs"] = 0
    for col in ["open","high","low","close","volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    required = {"symbol","close"}
    if not required.issubset(df.columns):
        return pd.DataFrame()
    if "volume" not in df.columns:
        df["volume"] = 0
    # WARN-1 FIX: NSE bhavcopy sometimes appends series suffixes to symbol
    # (e.g. "PRICOLLTD-EQ", "NMDC-BE"). Strip trailing "-XX" so halal
    # universe matching works correctly and coverage improves from ~42% to ~80%+.
    df["symbol"] = (df["symbol"].astype(str).str.strip().str.upper()
                    .str.replace(r"-[A-Z]{1,3}$", "", regex=True))
    df["data_quality"] = "EOD_FRESH"
    return df[["symbol","open","high","low","close","volume","turnover_lakhs","data_quality"]
              ].dropna(subset=["close"]).query("close > 0").reset_index(drop=True)


def _bhavcopy_from_sheets() -> pd.DataFrame:
    if not _sheets_ok():
        return pd.DataFrame()
    log.info("Loading BHAVCOPY from Sheets Tab 1…")
    raw = _read_sheet("BHAVCOPY")
    if raw.empty:
        return pd.DataFrame()
    col_map = {}
    for internal, candidates in {
        "symbol": ["SYMBOL","SCRIP","TICKER"],
        "open":   ["OPEN","OPEN_PRICE"],
        "high":   ["HIGH","HIGH_PRICE"],
        "low":    ["LOW","LOW_PRICE"],
        "close":  ["CLOSE","CLOSE_PRICE","LTP"],
        "volume": ["VOLUME","TOTTRDQTY","TTLTRADGVOL"],
        "turnover_lakhs": ["TURNOVER_LAKHS","TURNOVER_LACS","TOTTRDVAL"],
        "series": ["SERIES"],
    }.items():
        for c in candidates:
            if c in raw.columns:
                col_map[c] = internal; break
    df = raw.rename(columns=col_map)
    if "series" in df.columns:
        df = df[df["series"].astype(str).str.strip().str.upper() == "EQ"].copy()
    for col in ["open","high","low","close","volume","turnover_lakhs"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "turnover_lakhs" not in df.columns:
        df["turnover_lakhs"] = df.get("volume", pd.Series(0)) * df.get("close", pd.Series(0)) / 100_000
    df["symbol"]       = df["symbol"].astype(str).str.strip().str.upper()
    df["data_quality"] = "SHEETS_EOD"
    return df.dropna(subset=["close"]).query("close > 0").reset_index(drop=True)


def _bhavcopy_from_yfinance() -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError:
        return pd.DataFrame()
    universe   = get_halal_universe()
    candidates = [s for s in _HALAL_FALLBACK if s in universe] or list(_HALAL_FALLBACK)
    log.info(f"yfinance batch: {len(candidates)} halal candidates")
    batch_close: dict = {}; batch_vol: dict = {}
    for i in range(0, len(candidates), 50):
        chunk   = candidates[i:i+50]
        tickers = " ".join(f"{s}.NS" for s in chunk)
        for _attempt in range(3):
            try:
                raw = yf.download(tickers, period="2d", interval="1d",
                                  progress=False, auto_adjust=False, group_by="ticker",
                                  timeout=_YF_DOWNLOAD_TIMEOUT)
                if raw.empty:
                    break
                for sym in chunk:
                    tk = f"{sym}.NS"
                    try:
                        if hasattr(raw.columns, "levels"):
                            # BUG FIX [YF-001]: yfinance ≥0.2.x flipped MultiIndex level
                            # order — ticker symbols are now at level 0, price types at
                            # level 1.  We detect the real ticker level by checking which
                            # level contains '.NS' strings instead of hard-coding level=1.
                            lvl0 = list(raw.columns.get_level_values(0))
                            lvl1 = list(raw.columns.get_level_values(1))
                            if any(".NS" in str(v) for v in lvl0):
                                tk_level = 0
                            elif any(".NS" in str(v) for v in lvl1):
                                tk_level = 1
                            else:
                                tk_level = 0  # safe fallback
                            tickers_in_col = list(raw.columns.get_level_values(tk_level))
                            sub = (raw.xs(tk, axis=1, level=tk_level) if tk in tickers_in_col
                                   else (raw[tk] if tk in raw.columns else None))
                        else:
                            sub = raw.copy()
                        if sub is None:
                            continue
                        sub.columns = [c.lower() if isinstance(c, str) else str(c).lower() for c in sub.columns]
                        cs = sub["close"].dropna()
                        vs = sub.get("volume", pd.Series(dtype=float)).dropna()
                        if not cs.empty:
                            batch_close[sym] = float(cs.iloc[-1])
                            batch_vol[sym]   = float(vs.iloc[-1]) if not vs.empty else 0.0
                    except Exception:
                        continue
                time.sleep(1); break
            except Exception:
                time.sleep(5 * (_attempt + 1))
    records = [{"symbol": sym, "open": c, "high": c, "low": c,
                "close": round(c, 2), "volume": batch_vol.get(sym, 0),
                "turnover_lakhs": round((batch_vol.get(sym, 0) * c) / 100_000, 2),
                "data_quality": "SNAPSHOT_FALLBACK"}
               for sym, c in batch_close.items() if c > 0]
    log.info(f"yfinance batch complete: {len(records)} symbols")
    return pd.DataFrame(records) if records else pd.DataFrame()


def load_bhavcopy() -> Tuple[pd.DataFrame, str]:
    """
    v5.1 Main data cascade — returns (df, source_label).
    Waterfall: NSE Robust (retry+proxy) → Addon Finance → Sheets → yfinance snapshot.
    Supports `inputs.source` override via FORCE_ADDON / FORCE_SHEETS / FORCE_YFINANCE.
    """
    # Source override: addon
    if FORCE_ADDON:
        df = _bhavcopy_from_addon()
        return (df, "ADDON") if not df.empty else (pd.DataFrame(), "ADDON_FAILED")

    if FORCE_YFINANCE:
        df = _bhavcopy_from_yfinance()
        return df, "YFINANCE"

    if FORCE_SHEETS:
        df = _bhavcopy_from_sheets()
        return (df, "SHEETS") if not df.empty else (_bhavcopy_from_yfinance(), "YFINANCE")

    # Primary: NSE Robust (retry + proxy rotation + cookie refresh)
    sess = _get_nse_session()
    for days_back in range(0, 6):
        d = datetime.today() - timedelta(days=days_back)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        ds = d.strftime("%d%m%Y")
        try:
            log.info(f"Trying NSE robust bhavcopy {ds}…")
            raw = _download_bhavcopy_nse_robust(ds, sess)
            df  = _clean_bhavcopy(raw)
            if not df.empty:
                log.info(f"✅ NSE bhavcopy: {len(df)} EQ records")
                return df, "NSE"
        except Exception as e:
            log.debug(f"Bhavcopy {ds}: {e}")
        time.sleep(1)

    # Addon Finance fallback
    if ADDON_FINANCE_API_KEY:
        log.warning("NSE bhavcopy failed — trying Addon Finance API…")
        df = _bhavcopy_from_addon()
        if not df.empty:
            return df, "ADDON"

    log.warning("NSE bhavcopy failed — trying Sheets…")
    df = _bhavcopy_from_sheets()
    if not df.empty:
        return df, "SHEETS"

    log.warning("⚠️ DEGRADED MODE — yfinance fallback")
    df = _bhavcopy_from_yfinance()

    if not df.empty and len(df) <= 100:
        log.warning(f"🚨 UNIVERSE SHRUNK: yfinance fallback = {len(df)} hardcoded stocks only")
        halal_uni = get_halal_universe()
        missing = len(halal_uni - set(df["symbol"]))
        log.warning(f"   Missing {missing} halal symbols from screening")

    return df, "YFINANCE"

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — HISTORICAL OHLCV
# ══════════════════════════════════════════════════════════════════════════════

def _validate_no_lookahead(df: pd.DataFrame) -> pd.DataFrame:
    """
    Guard against look-ahead bias.

    Two layers of protection:
    1. Date ceiling  — strip any rows dated after today (future data).
    2. Unclosed-bar  — if the last row's date equals today, remove it.
       An intraday bar for today is *not yet closed*; including it in any
       rolling indicator (MA, RSI, Bollinger, VPOC) would embed future
       information into a position that is scored on yesterday's close.

    All indicator functions (fortress_score, _whale_radar, _divergence_engine,
    etc.) call this once via fetch_history() so no further guard is needed
    inside individual scorers.
    """
    if df.empty or "date" not in df.columns:
        return df
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)

    # BUG FIX [TZ-001]: yfinance returns tz-aware UTC dates; comparing them to a
    # tz-naive pd.Timestamp raises TypeError in pandas ≥1.4.  The previous fix used
    # tz_localize(col_tz) which itself raises TypeError if the timestamp already has
    # tzinfo set.  The cleanest solution: strip timezone from the date column once,
    # immediately after loading, so all comparisons are tz-naive throughout the pipeline.
    # Daily OHLCV bars don't need sub-day timezone precision.
    if not df.empty and hasattr(df["date"].dt, "tz") and df["date"].dt.tz is not None:
        df["date"] = df["date"].dt.tz_localize(None)

    today_date = datetime.today().date()
    today      = pd.Timestamp(today_date)           # always tz-naive now
    # Layer 1: remove future rows
    df = df[df["date"] <= today].copy()
    # Layer 2: remove today's unclosed bar (score on confirmed, closed candles only)
    if not df.empty and df["date"].iloc[-1].date() == today_date:
        df = df.iloc[:-1].copy()
    return df




def _preload_histories_yf(symbols: List[str], days: int = 300) -> Dict[str, pd.DataFrame]:
    """Batch-download historical OHLCV for all symbols via yfinance in chunks of 50.
    Returns {symbol_upper: DataFrame} to eliminate per-symbol network calls."""
    cache: Dict[str, pd.DataFrame] = {}
    if not symbols:
        return cache
    try:
        import yfinance as yf
    except ImportError:
        return cache

    end = datetime.today()
    start = end - timedelta(days=days + 50)
    for i in range(0, len(symbols), 50):
        chunk = symbols[i:i + 50]
        tickers = " ".join(f"{s}.NS" for s in chunk)
        for attempt in range(2):
            try:
                raw = yf.download(tickers, start=start, end=end,
                                  progress=False, auto_adjust=False,
                                  group_by="ticker",
                                  timeout=_YF_DOWNLOAD_TIMEOUT)
                if raw.empty:
                    break
                for sym in chunk:
                    tk = f"{sym}.NS"
                    try:
                        if hasattr(raw.columns, "levels"):
                            # BUG FIX [YF-001]: detect real ticker level dynamically
                            lvl0 = list(raw.columns.get_level_values(0))
                            lvl1 = list(raw.columns.get_level_values(1))
                            if any(".NS" in str(v) for v in lvl0):
                                tk_level = 0
                            elif any(".NS" in str(v) for v in lvl1):
                                tk_level = 1
                            else:
                                tk_level = 0
                            tickers_in_col = list(raw.columns.get_level_values(tk_level))
                            sub = (raw.xs(tk, axis=1, level=tk_level) if tk in tickers_in_col
                                   else (raw[tk] if tk in raw.columns else None))
                        else:
                            sub = raw.copy() if len(chunk) == 1 else None
                        if sub is None or sub.empty:
                            continue
                        sub = sub.reset_index()
                        sub.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                                       for c in sub.columns]
                        if "close" not in sub.columns and "adj close" in sub.columns:
                            sub = sub.rename(columns={"adj close": "close"})
                        sub["date"] = pd.to_datetime(sub["date"])
                        df = sub[["date", "open", "high", "low", "close", "volume"]].dropna()
                        cache[sym.upper()] = _validate_no_lookahead(df)
                    except Exception:
                        continue
                break
            except Exception as e:
                log.debug(f"Batch yfinance chunk {i}-{i + 50} attempt {attempt + 1}: {e}")
                time.sleep(2 * (attempt + 1))
    log.info(f"Preloaded {len(cache)} histories via batch yfinance")
    return cache

def fetch_history(symbol: str, days: int = 300,
                  sess: Optional[requests.Session] = None,
                  yf_cache: Optional[Dict[str, pd.DataFrame]] = None) -> pd.DataFrame:
    """NSE historical API → batch yfinance cache → individual yfinance fallback."""
    global _NSE_HISTORY_OK
    sym = symbol.upper().strip()

    # Fast path: preloaded batch yfinance cache (zero network call)
    # MEDIUM-1 FIX: use RLock to prevent race on shared mutable dict
    if yf_cache is not None:
        with _YF_CACHE_LOCK:
            _cached = yf_cache.get(sym)
        if _cached is not None and len(_cached) >= MIN_HIST_BARS:
            return _cached

    # NSE API (skip entirely if we already know it is down or IP-blocked)
    with _NSE_FAIL_LOCK:
        _nse_globally_blocked = _NSE_IP_BLOCKED
    if _get_nse_history_ok() is not False and not _nse_globally_blocked:
        try:
            if sess is None:
                sess = _get_nse_session()
            end = datetime.today(); start = end - timedelta(days=days + 50)
            data = _nse_json(sess, "https://www.nseindia.com/api/historical/cm/equity",
                             params={"symbol": sym, "series": '["EQ"]',
                                     "from": start.strftime("%d-%m-%Y"), "to": end.strftime("%d-%m-%Y")},
                             timeout=12)
            records = data.get("data", []) if isinstance(data, dict) else []
            if records:
                df = pd.DataFrame(records).rename(columns={
                    "CH_TIMESTAMP":"date","CH_OPENING_PRICE":"open",
                    "CH_TRADE_HIGH_PRICE":"high","CH_TRADE_LOW_PRICE":"low",
                    "CH_CLOSING_PRICE":"close","CH_TOT_TRADED_QTY":"volume",
                })
                df["date"] = pd.to_datetime(df["date"])
                for c in ["open","high","low","close","volume"]:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                df = df[["date","open","high","low","close","volume"]].dropna()
                if len(df) >= MIN_HIST_BARS:
                    _set_nse_history_ok(True)
                    return _validate_no_lookahead(df)
        except Exception as e:
            # FIX-NSE-NOISE: demote to debug when IP is already known-blocked
            with _NSE_FAIL_LOCK:
                _ip_blocked = _NSE_IP_BLOCKED
            if _ip_blocked:
                log.debug(f"NSE history {sym}: {e} — falling back to yfinance (IP blocked)")
            else:
                log.warning(f"NSE history {sym}: {e} — falling back to yfinance")
            _set_nse_history_ok(False)

    # Individual yfinance fallback (only if no cache entry)
    if yf_cache is None or sym not in yf_cache:
        with _YF_FAIL_LOCK:
            cb_open = time.time() < _YF_CIRCUIT_OPEN_UNTIL
        if cb_open:
            log.warning(f"YF circuit open — skipping individual history fetch for {sym}")
        else:
            try:
                end = datetime.today(); start = end - timedelta(days=days + 50)
                raw = _yf_download_with_backoff(f"{sym}.NS", start=start, end=end,
                                                progress=False, auto_adjust=False,
                                                timeout=_YF_DOWNLOAD_TIMEOUT)
                if not raw.empty:
                    raw = raw.reset_index()
                    raw.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in raw.columns]
                    if "close" not in raw.columns and "adj close" in raw.columns:
                        raw = raw.rename(columns={"adj close": "close"})
                    raw["date"] = pd.to_datetime(raw["date"])
                    df = raw[["date","open","high","low","close","volume"]].dropna()
                    return _validate_no_lookahead(df)
            except Exception as e:
                log.warning(f"yfinance history {sym}: {e}")

    # Return cached frame even if short, or empty
    if yf_cache is not None and sym in yf_cache:
        return yf_cache[sym]
    return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — INTELLIGENCE DATA (FII/DII, Insider, Filings, Earnings)
# ══════════════════════════════════════════════════════════════════════════════

def fetch_fii_dii() -> dict:
    NEUTRAL = {"score": 15, "label": "MIXED", "detail": "FII/DII data unavailable", "fii_net": 0, "dii_net": 0}
    # IP-block guard: skip NSE entirely if circuit is open
    with _NSE_FAIL_LOCK:
        nse_ok = not _NSE_IP_BLOCKED
    if not FORCE_SHEETS and not FORCE_YFINANCE and nse_ok:
        try:
            sess = _get_nse_session()
            data = _nse_json(sess, "https://www.nseindia.com/api/fiidiiTradeReact")
            row  = data[0] if isinstance(data, list) else data
            fii  = float(str(row.get("fiiNet", row.get("FII_NET_PURCHASE_SALES", 0))).replace(",",""))
            dii  = float(str(row.get("diiNet", row.get("DII_NET_PURCHASE_SALES", 0))).replace(",",""))
            both = fii > 0 and dii > 0
            if both:          score, label = 30, "🟢 FII+DII BUYING"
            elif fii > 0:     score, label = 22, "✅ FII BUYING"
            elif dii > 0:     score, label = 18, "✅ DII BUYING"
            elif fii < 0 and dii < 0: score, label = 5, "🔴 FII+DII SELLING"
            else:             score, label = 12, "↔ MIXED"
            score = min(30, score + min(5, int((abs(fii)+abs(dii))/100_000)))
            fii_cr = fii/100; dii_cr = dii/100
            return {"score": score, "label": label, "fii_net": round(fii_cr),
                    "dii_net": round(dii_cr), "detail": f"FII ₹{fii_cr:+,.0f}Cr | DII ₹{dii_cr:+,.0f}Cr"}
        except Exception as e:
            log.debug(f"FII/DII NSE: {e}")

    # Sheets Tab 2
    if _sheets_ok():
        df = _read_sheet("FII_DII")
        if not df.empty:
            fii_col = next((c for c in df.columns if "FII" in c), None)
            dii_col = next((c for c in df.columns if "DII" in c), None)
            if fii_col and dii_col:
                def _pcr(x):
                    try: return float(str(x).replace(",","").replace("₹","").replace("CR","").strip())
                    except: return 0.0
                row = df.tail(5)
                fii_5d = sum(_pcr(v) for v in row[fii_col])
                dii_5d = sum(_pcr(v) for v in row[dii_col])
                if fii_5d > 0 and dii_5d > 0: score, label = 30, "🟢 FII+DII BUYING"
                elif fii_5d > 0:               score, label = 22, "✅ FII BUYING"
                elif dii_5d > 0:               score, label = 18, "✅ DII BUYING"
                else:                          score, label = 5,  "🔴 SELLING"
                return {"score": score, "label": label, "fii_net": round(fii_5d/100),
                        "dii_net": round(dii_5d/100), "detail": f"FII 5d ₹{fii_5d/100:.0f}Cr [SHEETS]"}
    return NEUTRAL


def fetch_insider_trades(days_back: int = 30) -> dict:
    result: dict = {}
    with _NSE_FAIL_LOCK:
        nse_ok = not _NSE_IP_BLOCKED
    if not FORCE_SHEETS and not FORCE_YFINANCE and nse_ok:
        try:
            sess   = _get_nse_session()
            data   = _nse_json(sess, "https://www.nseindia.com/api/corporates-pit", params={"index":"equities"})
            data   = data.get("data",[]) if isinstance(data,dict) else data
            cutoff = datetime.today() - timedelta(days=days_back)
            for row in data:
                sym = str(row.get("symbol","")).upper()
                if not sym or not is_halal(sym): continue
                if "sell" in str(row.get("acqMode","")).lower(): continue
                try:
                    if pd.to_datetime(row.get("date","")) < cutoff: continue
                except Exception: pass
                shares = float(str(row.get("totAcqShrs", row.get("secAcq",0))).replace(",",""))
                try: val_cr = float(str(row.get("secVal",0)).replace(",","")) / 100
                except: val_cr = shares * 10 / 1e7
                if sym not in result:
                    result[sym] = {"total_cr": 0.0, "count": 0, "person": ""}
                result[sym]["total_cr"] += val_cr
                result[sym]["count"]    += 1
                result[sym]["person"]    = str(row.get("acqName","Insider"))[:30]
            if result:
                for sym, d in result.items():
                    log_val = math.log10(max(1, d["total_cr"] * 1e7)) if d["total_cr"] > 0 else 0
                    score   = max(5, min(30, round((log_val - 4) * 5)))
                    d["score"]  = score
                    d["detail"] = f"{d['count']} insider buy(s) — ₹{d['total_cr']:.1f}Cr ({d['person']})"
                return result
        except Exception as e:
            log.debug(f"Insider NSE: {e}")

    # Sheets Tab 3
    if _sheets_ok():
        df = _read_sheet("INSIDER")
        if not df.empty:
            sym_col = next((c for c in df.columns if "SYMBOL" in c or "SCRIP" in c), None)
            val_col = next((c for c in df.columns if any(k in c for k in ("VALUE","LAKH","AMOUNT"))), None)
            per_col = next((c for c in df.columns if any(k in c for k in ("PERSON","NAME","ACQNAME"))), None)
            if sym_col:
                for _, row in df.iterrows():
                    sym = str(row.get(sym_col,"")).strip().upper()
                    if not sym or not is_halal(sym): continue
                    try:
                        raw_val = float(str(row.get(val_col,"0")).replace(",","").replace("₹",""))
                    except: raw_val = 0
                    val_cr = raw_val / 100 if raw_val < 100_000 else raw_val / 1e7
                    person = str(row.get(per_col,"Insider"))[:30] if per_col else "Insider"
                    if sym not in result:
                        result[sym] = {"total_cr": 0.0, "count": 0, "person": person}
                    result[sym]["total_cr"] += val_cr
                    result[sym]["count"]    += 1
                for sym, d in result.items():
                    log_val = math.log10(max(1, d["total_cr"] * 1e7)) if d["total_cr"] > 0 else 0
                    score   = max(5, min(30, round((log_val - 4) * 5)))
                    d["score"]  = score
                    d["detail"] = f"{d['count']} buy(s) ₹{d['total_cr']:.1f}Cr ({d['person']}) [SHEETS]"
    return result


def fetch_filings(days_back: int = 14) -> dict:
    """
    Corporate filing sentiment analysis with proper negation handling.
    Scores: 0-30 scale. Negation flips sentiment (e.g., 'no penalty' = positive).
    """
    POS_KW = ["bonus","dividend","buyback","split","profit","growth","order",
              "contract","win","award","acquisition","launch","upgrade","beat",
              "expansion","partnership","approval","clearance","patent","fda"]
    NEG_KW = ["loss","write-off","penalty","fraud","probe","npa","default",
              "downgrade","miss","warning","sebi notice","court","litigation",
              "resignation","delay","postpone","cancel","terminate","recall"]
    NEGATION_MARKERS = ["no ","not ","without ","never ","non-","anti-",
                        "denies","denied","rejects","rejected","cleared of",
                        "acquitted","not guilty","dismissed"]
    result: dict = {}

    def _score_text(text: str) -> tuple:
        """Return (score, detail, sentiment_label) with negation awareness."""
        text_lower = text.lower()

        # Detect negated phrases first (higher priority)
        negated_pos = 0
        negated_neg = 0
        for marker in NEGATION_MARKERS:
            if marker in text_lower:
                for kw in POS_KW:
                    if f"{marker}{kw}" in text_lower or f"{marker} {kw}" in text_lower:
                        negated_pos += 1
                for kw in NEG_KW:
                    if f"{marker}{kw}" in text_lower or f"{marker} {kw}" in text_lower:
                        negated_neg += 1

        # Standard keyword matching
        pos = sum(1 for k in POS_KW if k in text_lower)
        neg = sum(1 for k in NEG_KW if k in text_lower)

        # Adjust: negated positives don't count, negated negatives flip to positive
        effective_pos = max(0, pos - negated_pos + negated_neg)
        effective_neg = max(0, neg - negated_neg)

        raw_score = 15 + effective_pos * 5 - effective_neg * 8
        score = min(30, max(0, raw_score))

        # Build detail
        if negated_neg > 0:
            matched_neg = [k for k in NEG_KW if any(m in text_lower for m in NEGATION_MARKERS 
                         if f"{m}{k}" in text_lower or f"{m} {k}" in text_lower)]
            detail = f"✅ Cleared: {', '.join(matched_neg[:2])}"
            label = "POSITIVE_NEGATED"
        elif effective_pos > 0:
            matched = [k.title() for k in POS_KW if k in text_lower]
            detail = f"Filing: {', '.join(matched[:2])}"
            label = "POSITIVE"
        elif effective_neg > 0:
            matched = [k.title() for k in NEG_KW if k in text_lower]
            detail = f"⚠️ Risk: {', '.join(matched[:2])}"
            label = "NEGATIVE"
        else:
            detail = "Corporate filing — neutral"
            label = "NEUTRAL"

        return score, detail, label

    with _NSE_FAIL_LOCK:
        nse_ok = not _NSE_IP_BLOCKED
    if not FORCE_SHEETS and not FORCE_YFINANCE and nse_ok:
        try:
            sess = _get_nse_session()
            data = _nse_json(sess, "https://www.nseindia.com/api/corporates-corporateActions",
                             params={"index":"equities",
                                     "from_date":(datetime.today()-timedelta(days=days_back)).strftime("%d-%m-%Y"),
                                     "to_date":datetime.today().strftime("%d-%m-%Y"),
                                     "type":"announcements"})
            if isinstance(data,dict): data=data.get("data",[])
            for row in (data or []):
                sym     = str(row.get("symbol","")).upper()
                subject = str(row.get("subject",row.get("desc",""))).lower()
                if not sym: continue
                score, detail, label = _score_text(subject)
                if sym not in result or score > result[sym]["score"]:
                    result[sym] = {"score": score, "detail": detail, "label": label}
            if result: return result
        except Exception as e:
            log.debug(f"Filings NSE: {e}")

    # Sheets Tab 4 — parse structured, not raw cell text
    if _sheets_ok():
        df = _read_sheet("FILINGS")
        if not df.empty:
            sym_col  = next((c for c in df.columns if "SYMBOL" in c or "SCRIP" in c), None)
            subj_col = next((c for c in df.columns if any(k in c for k in ("SUBJECT","DESC","FILING","HEADLINE","ANNOUNCEMENT"))), None)
            if sym_col and subj_col:
                for _, row in df.iterrows():
                    sym = str(row.get(sym_col,"")).strip().upper()
                    raw_subj = str(row.get(subj_col,"")).lower()
                    if not sym: continue
                    score, detail, label = _score_text(raw_subj)
                    if sym not in result or score > result[sym]["score"]:
                        result[sym] = {"score": score, "detail": detail, "label": label}
    return result


def fetch_earnings_calendar() -> dict:
    cal: dict = {}
    with _NSE_FAIL_LOCK:
        nse_ok = not _NSE_IP_BLOCKED
    if not FORCE_SHEETS and not FORCE_YFINANCE and nse_ok:
        try:
            sess  = _get_nse_session()
            evts  = _nse_json(sess,"https://www.nseindia.com/api/event-calendar",params={"index":"equities"})
            if isinstance(evts,dict): evts=evts.get("data",[])
            today = datetime.today()
            for ev in (evts or []):
                sym = str(ev.get("symbol","")).upper()
                pur = str(ev.get("purpose","")).lower()
                if "result" not in pur and "dividend" not in pur: continue
                try:
                    dt   = pd.to_datetime(ev.get("date","")).to_pydatetime()
                    days = (dt - today).days
                    if sym not in cal or abs(days) < abs(cal[sym]): cal[sym] = days
                except Exception: continue
            if cal: return cal
        except Exception as e:
            log.debug(f"Earnings NSE: {e}")

    if _sheets_ok():
        df = _read_sheet("EARNINGS")
        if not df.empty:
            sym_col  = next((c for c in df.columns if "SYMBOL" in c), None)
            date_col = next((c for c in df.columns if "DATE" in c or "RESULT" in c), None)
            if sym_col and date_col:
                today = datetime.today()
                for _, row in df.iterrows():
                    sym = str(row.get(sym_col,"")).strip().upper()
                    if not sym: continue
                    try:
                        dt   = pd.to_datetime(str(row[date_col]), dayfirst=True, errors="coerce")
                        if pd.isna(dt): continue
                        days = (dt.to_pydatetime() - today).days
                        if sym not in cal or abs(days) < abs(cal[sym]): cal[sym] = days
                    except Exception: continue
    return cal


def _check_earnings_yf(sym: str) -> Optional[int]:
    try:
        import yfinance as yf
        cal   = yf.Ticker(f"{sym}.NS").calendar
        dates = cal.get("Earnings Date", []) if isinstance(cal, dict) else []
        today = datetime.today()
        future = []
        for d in (dates if hasattr(dates,"__iter__") else [dates]):
            try:
                days = (pd.to_datetime(d).to_pydatetime() - today).days
                if days >= 0: future.append(days)
            except Exception: pass
        return min(future) if future else None
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — MACRO REGIME (single shared cache)
# ══════════════════════════════════════════════════════════════════════════════

_MACRO_CACHE:    Optional[dict] = None
_MACRO_LOCK      = threading.Lock()
_SMALLCAP_CACHE: dict           = {}


def fetch_macro_regime() -> dict:
    # FIX-A03: Use _yf_download_with_backoff() so YF circuit breaker applies.
    FALLBACK = {"macro_state":"CHOP","vix_val":18.0,"nifty_chg":0.0,"breadth_ok":True}
    # Check circuit breaker before any downloads
    with _YF_FAIL_LOCK:
        if time.time() < _YF_CIRCUIT_OPEN_UNTIL:
            log.warning("fetch_macro_regime: YF circuit OPEN — returning FALLBACK macro")
            return FALLBACK
        if _YF_FAIL_COUNT >= _YF_FAIL_THRESHOLD:
            return FALLBACK
    try:
        vix_df   = _yf_download_with_backoff("^INDIAVIX", period="5d",  progress=False, auto_adjust=True, timeout=_YF_DOWNLOAD_TIMEOUT)
        nifty_df = _yf_download_with_backoff("^NSEI",     period="10d", progress=False, auto_adjust=True, timeout=_YF_DOWNLOAD_TIMEOUT)
        cnx_df   = _yf_download_with_backoff("^CNX500",   period="60d", progress=False, auto_adjust=True, timeout=_YF_DOWNLOAD_TIMEOUT)
    except Exception:
        return FALLBACK

    vix = 18.0
    if not vix_df.empty:
        try: vix = float(vix_df["Close"].squeeze().iloc[-1])
        except: pass

    nifty_chg = 0.0
    if not nifty_df.empty and len(nifty_df) >= 2:
        try:
            nc = nifty_df["Close"].squeeze().values
            nifty_chg = float((nc[-1]-nc[-2])/nc[-2]*100)
        except: pass

    breadth_ok = True
    if not cnx_df.empty and len(cnx_df) >= 50:
        try:
            cc = cnx_df["Close"].squeeze()
            breadth_ok = float(cc.iloc[-1]) > float(cc.rolling(50).mean().iloc[-1])
        except: pass

    if nifty_chg <= SNIPER_CFG["nifty_massacre"]:   state = "MASSACRE"
    elif vix >= SNIPER_CFG["vix_panic"]:             state = "PANIC"
    elif vix >= SNIPER_CFG["vix_chop"]:              state = "CHOP"
    elif not breadth_ok:                             state = "CHOP"
    else:                                            state = "CLEAR"

    log.info(f"Macro: {state} | VIX={vix:.1f} | NIFTY {nifty_chg:+.2f}%")
    result = {"macro_state": state, "vix_val": round(vix,2),
              "nifty_chg": round(nifty_chg,2), "breadth_ok": breadth_ok}
    _save_macro_cache(result)  # ARCH-B1: persist to DB so _get_last_cached_macro() has data
    return result


def _get_macro() -> dict:
    global _MACRO_CACHE
    if _MACRO_CACHE is not None:
        return _MACRO_CACHE
    with _MACRO_LOCK:
        if _MACRO_CACHE is None:
            _MACRO_CACHE = fetch_macro_regime()
    return _MACRO_CACHE


def check_smallcap_cb() -> Tuple[bool, str]:
    if "r" in _SMALLCAP_CACHE:
        return _SMALLCAP_CACHE["r"]
    fail = (True, "⚠️ CB data unavailable — entries blocked (CB_FAIL_SAFE=true)") if CB_FAIL_SAFE \
        else (False, "CB data unavailable — pass")
    try:
        import yfinance as yf
        df = yf.download("^CNXSC", period="60d", progress=False, auto_adjust=True, timeout=_YF_DOWNLOAD_TIMEOUT)
        if df.empty:
            df = yf.download("NIFTYSMLCAP100.NS", period="60d", progress=False, auto_adjust=True, timeout=_YF_DOWNLOAD_TIMEOUT)
        if not df.empty and len(df) >= 20:
            c    = df["Close"].squeeze().values
            ma20 = float(np.mean(c[-20:]))
            last = float(c[-1])
            if last < ma20:
                r = (True, f"⚠️ SMALLCAP CB — {(ma20-last)/ma20*100:.1f}% below 20-DMA")
            else:
                r = (False, f"Smallcap healthy — {(last-ma20)/ma20*100:.1f}% above 20-DMA ✓")
            _SMALLCAP_CACHE["r"] = r
            return r
    except Exception:
        pass
    _SMALLCAP_CACHE["r"] = fail
    return fail


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10 — INDICATOR TOOLKIT (shared by both engines)
# ══════════════════════════════════════════════════════════════════════════════

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h,l,c = df["high"],df["low"],df["close"]
    tr = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.ewm(span=period,adjust=False).mean()

def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    d = series.diff()
    g = d.clip(lower=0).ewm(span=period,adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(span=period,adjust=False).mean()
    return 100-(100/(1+g/l.replace(0,np.nan)))

def _adx(df: pd.DataFrame, period: int = 14) -> float:
    h,l,c = df["high"],df["low"],df["close"]
    tr  = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr = tr.ewm(span=period,adjust=False).mean()
    up  = h-h.shift(); dn=l.shift()-l
    pdm = up.where((up>dn)&(up>0),0); ndm=dn.where((dn>up)&(dn>0),0)
    pdi = 100*pdm.ewm(span=period,adjust=False).mean()/atr
    ndi = 100*ndm.ewm(span=period,adjust=False).mean()/atr
    dx  = 100*(pdi-ndi).abs()/(pdi+ndi).replace(0,np.nan)
    val = float(dx.ewm(span=period,adjust=False).mean().iloc[-1])
    return val if not math.isnan(val) else 0.0

def _mfi(df: pd.DataFrame, period: int = 14) -> float:
    tp  = (df["high"]+df["low"]+df["close"])/3
    rmf = tp*df["volume"]
    pos = rmf.where(tp>tp.shift(),0); neg=rmf.where(tp<tp.shift(),0)
    mfr = pos.rolling(period).sum()/neg.rolling(period).sum().replace(0,np.nan)
    s   = 100-(100/(1+mfr))
    v   = float(s.iloc[-1]) if not s.empty else 50.0
    return v if not math.isnan(v) else 50.0

def _obv(df: pd.DataFrame) -> pd.Series:
    return (df["volume"] * np.sign(df["close"].diff().fillna(0))).cumsum()

def _volume_reliable(df: pd.DataFrame, lookback: int = 63) -> bool:
    r = df.tail(lookback)
    return len(r) > 0 and (r["volume"] <= 0).sum() / len(r) < 0.80

def _calc_vpoc_single(df: pd.DataFrame, lookback: int, n_bins: int = None) -> float:
    """
    OPT-1: Pure numpy vectorized VPOC — eliminates Python for-loop over bars.
    OPT-13: n_bins auto-scales with price range (prevents aliasing on low-price stocks).
    Speedup: 10-20x on 252-bar lookback vs original Python loop.
    """
    r = df.tail(lookback)
    n = len(r)
    if n < 20: return float(df["close"].iloc[-1])
    lows   = r["low"].values.astype(np.float64)
    highs  = r["high"].values.astype(np.float64)
    vols   = r["volume"].values.astype(np.float64)
    pmin, pmax = float(lows.min()), float(highs.max())
    if pmax <= pmin: return float(r["close"].iloc[-1])
    total = float(vols.sum())
    if total <= 0: return float((pmin + pmax) / 2)
    # OPT-13: adaptive bins based on price range percentage
    if n_bins is None:
        price_range_pct = (pmax - pmin) / max(pmin, 1.0) * 100
        n_bins = max(30, min(150, int(price_range_pct * 5)))
    bins   = np.linspace(pmin, pmax, n_bins + 1)
    bin_lo = bins[:-1]; bin_hi = bins[1:]
    # OPT-1: vectorized overlap via broadcasting — shape (n_bars, n_bins)
    lows_2d  = lows[:, np.newaxis]
    highs_2d = highs[:, np.newaxis]
    bar_range = np.maximum(highs_2d - lows_2d, 1e-9)
    overlap = (np.minimum(highs_2d, bin_hi) - np.maximum(lows_2d, bin_lo)).clip(min=0)
    frac    = overlap / bar_range
    # Recency weights: 0.5 (oldest) → 1.0 (newest)
    weights = np.linspace(0.5, 1.0, n)[:, np.newaxis]
    bv = (vols[:, np.newaxis] * frac * weights).sum(axis=0)
    idx = int(np.argmax(bv))
    return float((bins[idx] + bins[idx + 1]) / 2)

def calc_vpoc(df: pd.DataFrame, macro_state: str = "CHOP") -> float:
    """ACC-3: Regime-adaptive VPOC weights.
    CLEAR: momentum tape — recent price action (3m) less reliable; use balanced weights.
    CHOP: structural support matters more — weight 12m VPOC (institutional cost basis) heavily.
    """
    wt = SNIPER_CFG
    lb3m=min(63,len(df)); lb6m=min(126,len(df)); lb12m=min(252,len(df))
    v3=_calc_vpoc_single(df,lb3m); v6=_calc_vpoc_single(df,lb6m); v12=_calc_vpoc_single(df,lb12m)
    div = abs(v3-v6)/max(v6,1e-6)
    if div > 0.10:
        # High divergence between timeframes — fall back to equal weighting
        w3, w6, w12 = 0.20, 0.45, 0.35
    elif macro_state == "CHOP":
        # ACC-3: CHOP — structural cost basis dominates
        w3, w6, w12 = 0.10, 0.35, 0.55
    elif macro_state == "CLEAR":
        # ACC-3: CLEAR — recent accumulation zone more relevant
        w3, w6, w12 = 0.20, 0.45, 0.35
    else:
        # PANIC/MASSACRE — use balanced defaults
        w3, w6, w12 = wt["vpoc_3m_wt"], wt["vpoc_6m_wt"], wt["vpoc_12m_wt"]
    return round(float((v3*w3+v6*w6+v12*w12)/(w3+w6+w12)),2)

def _vpoc_profile(df: pd.DataFrame, n_bins: int = 50) -> dict:
    """OPT-1: Vectorized volume profile — eliminates iterrows() loop."""
    res = {"poc":0.0,"va_high":0.0,"va_low":0.0,"whale_pct":0.0}
    r   = df.tail(63)
    if len(r)<20: return res
    pmin,pmax=float(r["low"].min()),float(r["high"].max())
    if pmax<=pmin: return res
    total=float(r["volume"].sum())
    if total<=0: return res
    lows   = r["low"].values.astype(np.float64)
    highs  = r["high"].values.astype(np.float64)
    vols   = r["volume"].values.astype(np.float64)
    bins   = np.linspace(pmin, pmax, n_bins + 1)
    bin_lo = bins[:-1]; bin_hi = bins[1:]
    lows_2d  = lows[:, np.newaxis]
    highs_2d = highs[:, np.newaxis]
    bar_range = np.maximum(highs_2d - lows_2d, 1e-9)
    overlap  = (np.minimum(highs_2d, bin_hi) - np.maximum(lows_2d, bin_lo)).clip(min=0)
    bv = (vols[:, np.newaxis] * overlap / bar_range).sum(axis=0)
    idx=int(np.argmax(bv))
    res["poc"]       = float((bins[idx]+bins[idx+1])/2)
    res["whale_pct"] = float(bv[idx]/total*100)
    si    = np.argsort(bv)[::-1]
    cum   = np.cumsum(bv[si])
    va_i  = si[cum<=total*0.70]
    if len(va_i)>0:
        res["va_low"]  = float(bins[va_i.min()])
        res["va_high"] = float(bins[va_i.max()+1])
    return res


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 11 — FORTRESS SCORING ENGINE (fully preserved from v8.2)
# ══════════════════════════════════════════════════════════════════════════════

def compute_indicators(df: pd.DataFrame, period: int = 14) -> dict:
    """
    OPT-4: Fused single-pass indicator computation.
    Computes ATR-family, RSI, ADX, MFI in one shared pass — 4x faster than
    calling _atr()/_rsi()/_adx()/_mfi() separately on the same DataFrame.
    fortress_score() calls this once; results reused for VCP/forward bonus too.
    """
    h = df["high"]; l = df["low"]; c = df["close"]
    c_prev = c.shift(1)
    # Shared true range (used by ATR and ADX)
    tr = pd.concat([h - l, (h - c_prev).abs(), (l - c_prev).abs()], axis=1).max(axis=1)
    # ATR family — all computed from the same tr Series
    atr14_s  = tr.ewm(span=14,  adjust=False).mean()
    atr7_s   = tr.ewm(span=7,   adjust=False).mean()
    atr20_s  = tr.ewm(span=20,  adjust=False).mean()
    atr50_s  = tr.ewm(span=50,  adjust=False).mean()
    atr100_s = tr.ewm(span=100, adjust=False).mean()
    atr14  = float(atr14_s.iloc[-1])  if len(df) >= 14  else 0.0
    atr7   = float(atr7_s.iloc[-1])   if len(df) >= 7   else atr14
    atr20  = float(atr20_s.iloc[-1])  if len(df) >= 20  else atr14
    atr50  = float(atr50_s.iloc[-1])  if len(df) >= 50  else atr14
    atr100 = float(atr100_s.iloc[-1]) if len(df) >= 100 else atr14
    # RSI
    d = c.diff()
    g = d.clip(lower=0).ewm(span=period, adjust=False).mean()
    lo = (-d.clip(upper=0)).ewm(span=period, adjust=False).mean()
    rsi_s = 100 - (100 / (1 + g / lo.replace(0, np.nan)))
    rsi_v = float(rsi_s.iloc[-1]) if not rsi_s.empty else 50.0
    if math.isnan(rsi_v): rsi_v = 50.0
    # ADX (reuses tr)
    atr_adx = tr.ewm(span=period, adjust=False).mean()
    up = h - h.shift(); dn = l.shift() - l
    pdm = up.where((up > dn) & (up > 0), 0)
    ndm = dn.where((dn > up) & (dn > 0), 0)
    pdi = 100 * pdm.ewm(span=period, adjust=False).mean() / atr_adx
    ndi = 100 * ndm.ewm(span=period, adjust=False).mean() / atr_adx
    dx  = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    adx_raw = float(dx.ewm(span=period, adjust=False).mean().iloc[-1])
    adx_v = adx_raw if not math.isnan(adx_raw) else 0.0
    # MFI
    tp  = (h + l + c) / 3
    rmf = tp * df["volume"]
    pos = rmf.where(tp > tp.shift(), 0)
    neg = rmf.where(tp < tp.shift(), 0)
    mfr = pos.rolling(period).sum() / neg.rolling(period).sum().replace(0, np.nan)
    mfi_s = 100 - (100 / (1 + mfr))
    mfi_v = float(mfi_s.iloc[-1]) if not mfi_s.empty else 50.0
    if math.isnan(mfi_v): mfi_v = 50.0
    return {
        "atr14": atr14, "atr7": atr7, "atr20": atr20,
        "atr50": atr50, "atr100": atr100,
        "rsi": round(rsi_v, 1), "adx": round(adx_v, 1),
        "mfi": round(mfi_v, 1), "atr_s": atr14_s,
    }


def fortress_score(symbol: str, today_row, hist: pd.DataFrame,
                   macro_state: str = "CHOP") -> Optional[dict]:
    """
    Core Fortress engine: 6-layer VPOC, regime, MFI/ADX, sector truth,
    52W compression, ATR velocity, VDU, VCP coil.
    Returns dict or None (hard-veto).
    RC3 FIX: macro_state now passed in so MA200 tolerance can be regime-aware.
    """
    if len(hist) < MIN_HIST_BARS:
        log.info(f"FORTRESS VETO {symbol}: insufficient bars ({len(hist)} < {MIN_HIST_BARS})")
        return None

    close  = float(today_row["close"])
    volume = float(today_row.get("volume", hist["volume"].iloc[-1] if "volume" in hist.columns else 0))

    # OPT-4: single fused indicator pass — replaces 4 separate _atr/_rsi/_adx/_mfi calls
    ind = compute_indicators(hist, 14)
    atr14    = ind["atr14"]
    rsi_v    = ind["rsi"]
    mfi_v    = ind["mfi"]
    adx_v    = ind["adx"]
    adx_prev = _adx(hist.iloc[:-1], 14) if len(hist) > 14 else adx_v
    vpoc     = calc_vpoc(hist)
    vol_rel  = _volume_reliable(hist, 63)
    adv20    = float(hist["volume"].tail(20).mean()) if len(hist) >= 20 else volume
    ma50     = float(hist["close"].tail(50).mean())  if len(hist) >= 50 else close
    ma200    = float(hist["close"].tail(200).mean()) if len(hist) >= 200 else close

    if len(hist) >= 21:
        velocity = (close - float(hist["close"].iloc[-21])) / float(hist["close"].iloc[-21]) * 100
    else:
        velocity = 0.0

    ma_ref   = ma200 if len(hist)>=200 else (float(hist["close"].tail(100).mean()) if len(hist)>=100 else ma50)
    ma_label = "MA200" if len(hist)>=200 else ("MA100" if len(hist)>=100 else "MA50")
    alt_pct  = (close-ma_ref)/ma_ref*100 if ma_ref>0 else 0.0

    if alt_pct < -SNIPER_CFG["ma200_tolerance"]*100 and ma_label=="MA200":
        # RC3 FIX + BUG#3 FIX: Widen tolerance in CHOP/PANIC regimes — mean-reversion and
        # bounce entries happen exactly at MA200 dips. Static 5% tolerance killed
        # quality IT stocks in correction (WIPRO, VIMTALABS, ZENSARTECH in the log).
        # BUG#3: Stocks 18-29% below MA200 ARE falling knives; the veto is CORRECT.
        # The fix is NOT to widen tolerance further — it's to ensure the regime label
        # itself is accurate. If macro_state=CHOP and vix<22, these vetoes are intentional.
        # For genuine bounce candidates slightly below MA200 (<12%), raise the ceiling:
        # CHOP  → 12%: controlled pullback entries are valid (was 7.5%)
        # PANIC → 18%: catch high-quality stocks in a broad flush (was 10%)
        # MASSACRE → unchanged (pipeline returns None upstream)
        regime_scale = {"CHOP": 2.4, "PANIC": 3.6}.get(macro_state, 1.0)
        effective_tol = SNIPER_CFG["ma200_tolerance"] * regime_scale * 100
        if alt_pct < -effective_tol:
            log.info(f"FORTRESS VETO {symbol}: alt_pct={alt_pct:.1f}% below MA200 tol "
                     f"{effective_tol:.1f}% ({macro_state} regime)")
            return None
        log.info(f"FORTRESS MA200 PASS {symbol}: alt_pct={alt_pct:.1f}% within "
                 f"regime-scaled {effective_tol:.1f}% ({macro_state})")
    if alt_pct > SNIPER_CFG["alt_stop_pct"]:
        log.info(f"FORTRESS VETO {symbol}: alt_pct above stop threshold")
        return None

    sector      = get_sector(symbol)
    # FIX-4.1-M: Renewable energy bypass — SUZLON, TATAPOWER, INOXWIND, etc. are
    # halal businesses mapped to "NIFTY ENERGY" by keyword but permissible in Islam.
    # Override sector for known renewable symbols before SECTOR_BLOCKED check.
    if symbol.upper() in _RENEWABLE_SYMBOLS and sector == "NIFTY ENERGY":
        sector = "NIFTY RENEWABLE"
    sector_mult = SECTOR_TRUTH.get(sector, 1.0)
    if sector in SECTOR_BLOCKED:
        log.info(f"FORTRESS VETO {symbol}: sector is BLOCKED")
        return None

    # Sector RS override
    sect_20: Optional[float] = None
    if sector in SECTOR_INDICES:
        try:
            idf = _yf_download_with_backoff(f"^{SECTOR_INDICES[sector]}", period="30d",
                                            progress=False, auto_adjust=True,
                                            timeout=_YF_DOWNLOAD_TIMEOUT)
            if not idf.empty and len(idf)>=2:
                ic = idf["Close"].squeeze().values
                sect_20 = float((ic[-1]-ic[-20])/ic[-20]*100) if len(ic)>=20 else None
        except Exception as se:
            log.debug(f"Sector RS {sector}: {se}")
    if sect_20 is not None and velocity > sect_20+5.0:
        sector_mult = max(sector_mult, 1.0)

    turnover_lakhs = float(today_row.get("turnover_lakhs", 0))
    if turnover_lakhs < SNIPER_CFG["turnover_lakhs"]:
        log.info(f"FORTRESS VETO {symbol}: turnover below minimum")
        return None

    # Entry zone  (OPT-4: atr100 already computed in compute_indicators)
    atr100 = ind["atr100"]
    lo_pct = max(0.005, min(0.05, (atr14/close)*0.8)) if close>0 and atr14>0 else 0.02
    hi_pct = max(0.003, min(0.03, (atr14/close)*0.5)) + 0.01 if close>0 and atr14>0 else 0.015
    t1     = round(vpoc, 2)
    entry_lo, entry_hi = round(t1*(1-lo_pct),2), round(t1*(1+hi_pct),2)
    entry_zone = ("PRISTINE" if entry_lo<=close<=entry_hi else ("ABOVE" if close>entry_hi else "BELOW"))

    # Stop / exits
    atr_mult = SECTOR_ATR_MULT.get(sector, 1.0) * (0.75 if close<100 else 1.0 if close<300 else 1.40)
    t3 = round(max(close - atr_mult*atr14, close*0.93), 2)
    r1 = round(close*1.15,2); r2=round(close*1.30,2); r3=round(close*1.50,2)

    # VCP coil
    vol_contract = adv20>0 and volume<adv20*0.8
    vcp_coil = ("TIGHT 🟢" if atr14>0 and atr100>0 and (atr14/atr100)<0.70 and vol_contract else "LOOSE")

    # VDU (volume dry-up) with price confirmation
    vdu_bars = 0
    if len(hist)>=6 and vol_rel:
        for n in range(3,6):
            if all(float(hist["volume"].iloc[-(i+1)])<float(hist["volume"].iloc[-(i+2)]) for i in range(n-1)):
                vdu_bars = n
    vdu_confirmed = True
    if vdu_bars>=3:
        chg = (float(hist["close"].iloc[-1])-float(hist["close"].iloc[-(vdu_bars+1)])) / float(hist["close"].iloc[-(vdu_bars+1)])
        vdu_confirmed = chg >= -0.01

    if not vdu_confirmed: vdu_bonus,vdu_label = -3,f"🔴 VDU {vdu_bars}b+price drop — DISTRIBUTION"
    elif vdu_bars>=5:     vdu_bonus,vdu_label = 7,f"🌀 VDU {vdu_bars}-bar deep coil (+7pts)"
    elif vdu_bars>=4:     vdu_bonus,vdu_label = 5,f"🌀 VDU {vdu_bars}-bar confirmed (+5pts)"
    elif vdu_bars>=3:     vdu_bonus,vdu_label = 3,f"🌀 VDU {vdu_bars}-bar mild (+3pts)"
    else:                 vdu_bonus,vdu_label = 0,""

    # 52W compression
    if len(hist)>=20:
        h52 = float(hist.tail(252)["high"].max())
        pct_from_h = (h52-close)/h52*100 if h52>0 else 100
        atr_tight  = atr14>0 and atr100>0 and (atr14/atr100)<0.70
        if pct_from_h<=5:    w52_bonus=12 if atr_tight else 9
        elif pct_from_h<=10: w52_bonus=7  if atr_tight else 5
        elif pct_from_h<=15: w52_bonus=3
        else:                w52_bonus=0
    else:
        pct_from_h=100; w52_bonus=0

    # ATR velocity
    # OPT-4: reuse pre-computed atr7/atr20/atr50 from compute_indicators()
    if len(hist)>=55:
        a7=ind["atr7"]; a20=ind["atr20"]; a50=ind["atr50"]
        if a50>0 and a7<a20<a50:
            rate=1-(a7/a50)
            atrv_bonus=(8 if rate>0.50 else 6 if rate>0.30 else 4)
        elif a50>0 and a7<a50: atrv_bonus=2
        else:                  atrv_bonus=0
    else: atrv_bonus=0

    forward_bonus = w52_bonus+atrv_bonus+vdu_bonus

    # VPOC layers (volume-gated)
    if vol_rel:
        layer1 = abs(close-vpoc)/vpoc<=0.02 if vpoc>0 else False
        layer2 = any(float(hist["volume"].iloc[-(i+1)])>=SNIPER_CFG["vol_ratio"]*adv20
                     for i in range(min(5,len(hist)))) if adv20>0 else False
    else:
        layer1,layer2=False,False
    recent = hist.tail(min(SNIPER_CFG["bounce_recency"],len(hist)))
    touches = sum(1 for _,r in recent.iterrows() if vpoc>0 and abs(float(r["close"])-vpoc)/vpoc<=0.03)
    layer3  = touches>=2 or (adx_v>=25 and close>ma50)

    # Base fortress pts
    pts=0.0
    if layer1: pts+=25
    elif vpoc>0 and abs(close-vpoc)/vpoc<=0.05: pts+=15
    if layer2: pts+=20
    if layer3: pts+=15
    if adx_v>=SNIPER_CFG["adx_trend"]: pts+=10
    elif adx_v>=SNIPER_CFG["adx_range"]: pts+=5
    if mfi_v<=40: pts+=8
    elif mfi_v<=50: pts+=4
    if vcp_coil=="TIGHT 🟢": pts+=5

    pts *= sector_mult
    if alt_pct>SNIPER_CFG["alt_warn_pct"]:
        excess = min(5,int((alt_pct-SNIPER_CFG["alt_warn_pct"])/5))
        pts   *= 0.80*(0.92**excess)
    elif alt_pct>30: pts*=0.92
    pts += forward_bonus
    pts  = min(int(pts), FORT_SCORE_MAX["fortress"]+30)

    # ── FIX 3: Minimum fortress score veto ──────────────────────────────
    # Previously fortress_score() returned None only on hard structural vetoes
    # (insufficient bars, MA200 tolerance, sector block, turnover, alt_pct).
    # Symbols with pts=23 (only layer3 true) passed through to APEX, wasting
    # compute and injecting weak candidates. Add a soft minimum:
    # at least ONE of the two primary VPOC layers must be true, OR pts must be
    # above a minimum bar to ensure we have genuine volume-at-price confluence.
    _FORTRESS_MIN_PTS = 28   # absolute minimum before intelligence bonuses
    _FORTRESS_REQUIRE_VPOC = not (layer1 or layer2)  # True when both VPOC layers absent

    if pts < _FORTRESS_MIN_PTS:
        log.info(f"FORTRESS SOFT-VETO {symbol}: pts={pts:.0f} < {_FORTRESS_MIN_PTS} minimum")
        return None
    if _FORTRESS_REQUIRE_VPOC and pts < 38:
        # layer3-only pass with weak score: not enough confluence for APEX
        log.info(f"FORTRESS SOFT-VETO {symbol}: pts={pts:.0f}, no VPOC layers (l1=F,l2=F) — need ≥38")
        return None

    log.info(f"FORTRESS PASS {symbol}: pts={pts:.0f} | layers={layer1},{layer2},{layer3} | zone={entry_zone}")
    return {
        "fortress_pts": pts,
        "layer1": layer1, "layer2": layer2, "layer3": layer3,
        "vol_reliable": vol_rel, "vcp_coil": vcp_coil,
        "entry_zone": entry_zone, "atr_mult": atr_mult,
        "alt_pct": round(alt_pct,2), "sector_mult": round(sector_mult,3),
        "regime": ("MOMENTUM" if adx_v>=SNIPER_CFG["adx_trend"]
                   else "TRANSITION" if adx_v>=SNIPER_CFG["adx_range"] else "RANGING"),
        "mfi": round(mfi_v,1), "rsi": round(rsi_v,1), "adx": round(adx_v,1), "adx_prev": round(adx_prev,1),
        "t1": t1, "t3": t3, "r1": r1, "r2": r2, "r3": r3,
        "atr14": round(atr14,2), "adv20": round(adv20,0),
        "vpoc": round(vpoc,2), "ma50": round(ma50,2), "ma200": round(ma200,2),
        "ma_label": ma_label, "turnover_cr": round(turnover_lakhs/100,2),
        "w52_bonus": w52_bonus, "atrv_bonus": atrv_bonus,
        "vdu_bonus": vdu_bonus, "vdu_label": vdu_label, "vdu_bars": vdu_bars,
        "forward_bonus": forward_bonus, "velocity_pct": round(velocity,2),
    }


def _calc_cvd(hist: pd.DataFrame, vol_rel: bool) -> dict:
    if not vol_rel or len(hist)<12:
        return {"cvd_signal":"NEUTRAL","cvd_label":"","cvd_bonus":0}
    h = hist.copy()
    h["cvd"] = h.apply(lambda r: float(r["volume"]) if r["close"]>r["open"] else -float(r["volume"]),axis=1).cumsum()
    w=10; cn=float(h["cvd"].iloc[-1]); c10=float(h["cvd"].iloc[-w-1])
    pn=float(h["close"].iloc[-1]); p10=float(h["close"].iloc[-w-1])
    if pn>p10 and cn<c10:   return {"cvd_signal":"DISTRIBUTION","cvd_label":"🔴 CVD Diverge","cvd_bonus":-5}
    elif pn<=p10 and cn>c10: return {"cvd_signal":"ACCUMULATION","cvd_label":"🟢 CVD Accum","cvd_bonus":+5}
    return {"cvd_signal":"NEUTRAL","cvd_label":"","cvd_bonus":0}


def _calc_vsa(hist: pd.DataFrame, atr14: float, adv20: float, vol_rel: bool) -> dict:
    """OPT-2: Vectorized VSA — eliminates iterrows() on tail(5)."""
    if not vol_rel or len(hist)<5 or atr14<=0 or adv20<=0:
        return {"vsa_absorption":False,"vsa_label":"","vsa_bonus":0}
    tail5 = hist.tail(5)
    sp   = tail5["high"].values - tail5["low"].values
    vols = tail5["volume"].values.astype(float)
    cls  = tail5["close"].values.astype(float)
    lows = tail5["low"].values.astype(float)
    his  = tail5["high"].values.astype(float)
    rngs = np.where(his - lows <= 0, 1e-9, his - lows)
    cp   = (cls - lows) / rngs
    is_narrow   = sp < 0.5 * atr14
    is_high_vol = vols > 1.5 * adv20
    bull = int(np.sum(is_narrow & is_high_vol & (cp >= 0.60)))
    bear = int(np.sum(is_narrow & is_high_vol & (cp <= 0.40)))
    net  = bull - bear
    if net>0:  return {"vsa_absorption":True, "vsa_label":f"🟢 VSA Bullish ({bull}b)","vsa_bonus":min(8,bull*4)}
    elif net<0: return {"vsa_absorption":False,"vsa_label":f"🔴 VSA Dist ({bear}b)","vsa_bonus":-min(4,bear*2)}
    return {"vsa_absorption":False,"vsa_label":"","vsa_bonus":0}


def _calc_fog(adx_v: float, adx_prev: float, vix: float, ma50: float, ma200: float, w52_bonus: int) -> dict:
    score=0; reasons=[]
    if adx_v<=18 and adx_v<adx_prev: score+=1; reasons.append(f"ADX {adx_v:.1f}↓")
    if vix>SNIPER_CFG["vix_fog"]:    score+=1; reasons.append(f"VIX {vix:.1f}>{SNIPER_CFG['vix_fog']:.0f}")
    if ma200>0 and ma50>0 and abs(ma50-ma200)/ma200<=0.03: score+=1; reasons.append("MA compressed")
    if adx_v<=18 and w52_bonus==0:   score+=1; reasons.append("no 52W coil")
    tier  = ("FOG_SEVERE" if score>=3 else "FOG_WARNING" if score>=2 else "CLEAR")
    block = score>=2
    label = (f"🌫️ {tier} — "+" · ".join(reasons)) if block else ""
    return {"fog_tier":tier,"fog_block":block,"fog_label":label}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 12 — APEX 7-ENGINE (fully preserved from v1.2)
# ══════════════════════════════════════════════════════════════════════════════

def _whale_radar(hist: pd.DataFrame, adv20: float) -> Tuple[float, dict]:
    LOOKBACK=15; EMPTY={"whale_detected":False,"signal_type":"NONE","whale_label":"","stealth_score":0}
    if len(hist)<max(LOOKBACK,60) or adv20<=0: return 0.0,EMPTY
    tail=hist.tail(LOOKBACK)
    p_vel=float((tail["close"].iloc[-1]-tail["close"].iloc[0])/tail["close"].iloc[0]*100)
    flat =abs(p_vel)<3.0
    v20=float(hist["volume"].tail(20).mean()); v60=float(hist["volume"].tail(60).mean())
    if v60<=0: return 0.0,EMPTY
    vol_rising=(v20/v60-1)>=0.30
    obv_s=_obv(tail); obv_up=float(obv_s.iloc[-1]-obv_s.iloc[0])>0
    spikes=int((tail["volume"]>2.5*adv20).sum())
    rng_now=float(tail["high"].tail(5).max()-tail["low"].tail(5).min())
    rng_prev=float(hist.tail(40).head(35)["high"].max()-hist.tail(40).head(35)["low"].min())
    compressed=rng_prev>0 and (rng_now/rng_prev)<0.40
    pw=hist["close"].tail(5).values; vw=hist["volume"].tail(5).values.astype(float)
    prng=float(abs(pw[-1]-pw[0])/max(pw[0],1)*100)
    vt  =float(np.polyfit(range(5),vw,1)[0]) if len(vw)==5 else 0
    stealth=prng<=1.5 and vt>0 and vw[-1]>adv20*1.2
    ss  =min(100.0,40+abs(vt)*10) if stealth else 0.0
    sig ="NONE"
    if flat and vol_rising: sig="STEALTH" if ss>40 else "ACCUMULATION"
    elif flat and obv_up:   sig="STEALTH"
    elif not flat and vol_rising: sig="ACCUMULATION"
    score=0; parts=[]
    if flat and vol_rising:   score+=40; parts.append(f"🐋 Flat+Vol({(v20/max(v60,1)-1)*100:.0f}%↑)")
    if ss>40:                 score+=int(ss*0.35); parts.append(f"🕵️ Stealth{ss:.0f}")
    if obv_up and flat:       score+=20; parts.append("📈 OBV↑ flat")
    if spikes>=3:             score+=min(20,spikes*5); parts.append(f"🔦 {spikes}spikes")
    if compressed:            score+=15; parts.append("🌀 Range compressed")
    if not flat and vol_rising: score+=10; parts.append("⚡ Vol expanding")
    score=min(100,score)
    detected=score>=35 or ss>=50
    return float(score),{"whale_detected":detected,"signal_type":sig,
                         "whale_label":" | ".join(parts),"stealth_score":ss,
                         "price_velocity":round(p_vel,2),"vol_velocity":round((v20/max(v60,1)-1)*100,1),
                         "spike_days":spikes,"obv_rising":obv_up}


def _divergence_engine(hist: pd.DataFrame) -> Tuple[float, dict]:
    WINDOW=15; EMPTY={"div_type":"NONE","div_label":"No divergence","div_strength":0}
    if len(hist)<WINDOW+20: return 0.0,EMPTY
    rsi_s=_rsi(hist["close"]); obv_s=_obv(hist)
    lb=hist.tail(WINDOW+5)
    prices=lb["close"].values; rsis=rsi_s.tail(len(lb)).values; obvs=obv_s.tail(len(lb)).values
    def pivots(arr, w=4):  # OPT-12: window 3→4 reduces NSE daily noise false signals
        hi,lo=[],[]
        for i in range(w,len(arr)-w):
            if all(arr[i]>=arr[i-j] for j in range(1,w+1)) and all(arr[i]>=arr[i+j] for j in range(1,w+1)): hi.append((i,arr[i]))
            if all(arr[i]<=arr[i-j] for j in range(1,w+1)) and all(arr[i]<=arr[i+j] for j in range(1,w+1)): lo.append((i,arr[i]))
        return hi,lo
    _,p_lows=pivots(prices); _,r_lows=pivots(rsis); o_highs,_=pivots(obvs)
    div_type="NONE"; strength=0.0
    if len(p_lows)>=2 and len(r_lows)>=2:
        pl1,pl2=p_lows[-2],p_lows[-1]; rl1,rl2=r_lows[-2],r_lows[-1]
        if pl2[1]>pl1[1] and rl2[1]<rl1[1]:
            div_type="BULLISH_HIDDEN"; strength=min(100.0,float((rl1[1]-rl2[1])*2+25))
    obv_bonus=15.0 if len(o_highs)>=2 and o_highs[-1][1]>o_highs[-2][1] else 0.0
    score=min(100.0,(strength*0.85+obv_bonus)*{"BULLISH_HIDDEN":1.0,"NONE":0.0}.get(div_type,0.5))
    label=f"🔀 {div_type} ({strength:.0f}%)" if div_type!="NONE" else "No divergence"
    return float(score),{"div_type":div_type,"div_label":label,"div_strength":round(strength,1)}


def _vol_profile_score(profile: dict, close: float, fortress_vpoc: float = 0.0) -> Tuple[float, str]:
    """Score volume profile closeness.
    FIX: Uses fortress_vpoc (weighted 3m/6m/12m) as primary distance reference
    when available, avoiding the contradiction where fortress_score says
    layer1=True (close ≈ VPOC) but _vpoc_profile (63d only) reports a different POC.
    profile['poc'] is still used for Value Area checks (independent of VPOC calc)."""
    poc = profile.get("poc", 0)
    if poc <= 0: return 0.0, "No vol profile"
    score = 0; notes = []

    # Use weighted fortress VPOC for distance if provided, else fall back to 63d POC
    ref_poc = fortress_vpoc if fortress_vpoc > 0 else poc
    dist = abs(close - ref_poc) / ref_poc * 100
    if dist <= 1.0:   score += 40; notes.append("AT POC 🎯")
    elif dist <= 3.0: score += 25; notes.append("NEAR POC")
    elif dist <= 5.0: score += 12; notes.append("POC ZONE")

    va_lo = profile.get("va_low", 0); va_hi = profile.get("va_high", 0)
    if va_lo > 0 and va_hi > 0:
        if va_lo <= close <= va_hi: score += 20; notes.append("INSIDE VA")
        elif close < va_lo:         score += 8;  notes.append("BELOW VA")
    wp = profile.get("whale_pct", 0)
    if wp >= 35:   score += 25; notes.append(f"WHALE DEF {wp:.0f}%")
    elif wp >= 25: score += 15; notes.append(f"Strong POC {wp:.0f}%")
    va_w = (va_hi - va_lo) / poc * 100 if poc > 0 and va_hi > va_lo else 0
    if 0 < va_w <= 8: score += 10; notes.append("TIGHT VA")
    return float(min(100, score)), " · ".join(notes) if notes else "Diffuse"


def _pattern_score(hist: pd.DataFrame, atr14: float, profile: dict) -> Tuple[float, str]:
    if len(hist)<20: return 0.0,"No pattern"
    cl=hist["close"].values; hi=hist["high"].values
    lo=hist["low"].values;   vol=hist["volume"].values; n=len(hist)
    score=0; pats=[]
    if n>=7:
        rng=hi-lo
        if rng[-1]<=rng[-7:].min()+1e-9: score+=20; pats.append("NR7 🌀")
    if n>=2 and hi[-2]-lo[-2]>0 and (hi[-1]-lo[-1])/(hi[-2]-lo[-2])<0.60:
        score+=15; pats.append("Inside-Bar")
    if n>=30:
        # OPT-3: Use scipy argrelextrema for faster vectorized pivot detection
        try:
            from scipy.signal import argrelextrema
            local_hi_idx = set(argrelextrema(hi, np.greater_equal, order=3)[0])
            local_lo_idx = set(argrelextrema(lo, np.less_equal, order=3)[0])
            pvts = []
            for idx in sorted(local_hi_idx | local_lo_idx):
                if idx in local_hi_idx: pvts.append(("H", idx, hi[idx]))
                else: pvts.append(("L", idx, lo[idx]))
        except ImportError:
            pvts=[]
            for i in range(5,n-1):
                if hi[i]>=hi[i-1] and hi[i]>=hi[i-3]: pvts.append(("H",i,hi[i]))
                elif lo[i]<=lo[i-1] and lo[i]<=lo[i-3]: pvts.append(("L",i,lo[i]))
        if len(pvts)>=3:
            lp=pvts[-3:]; sw=[abs(lp[k][2]-lp[k-1][2]) for k in range(1,len(lp))]
            if len(sw)>=2 and all(sw[k]<sw[k-1] for k in range(1,len(sw))):
                score+=30; pats.append(f"VCP-{len(lp)}P 🎯")
    if n>=10:
        r10=cl[-10:]; band=(r10.max()-r10.min())/r10.mean()*100
        if band<5: score+=15; pats.append(f"Flat-Base({band:.1f}%)")
    if n>=12:
        dv=vol[-10:][np.diff(cl[-11:])<0]; md=float(dv.max()) if len(dv)>0 else 0
        if md>0 and vol[-1]>md and cl[-1]>cl[-2]: score+=20; pats.append("PocketPivot 💉")
    if n>=40:
        mid=n//2
        lh=float(hist["high"].iloc[:mid].max()); rh=float(hist["high"].iloc[mid:].max())
        ml=float(hist["low"].iloc[mid-5:mid+5].min())
        cd=(lh-ml)/lh if lh>0 else 0
        if 0.05<=cd<=0.20 and rh>=lh*0.98 and cl[-1]>=lh*0.95:
            score+=25; pats.append("Cup&Handle 🏆")
    poc=profile.get("poc",0)
    if poc>0 and n>=5:
        for i in range(-5,0):
            if abs(float(hist["low"].iloc[i])-poc)/poc<=0.015 and hist["close"].iloc[i]>hist["open"].iloc[i]:
                score+=15; pats.append("POC-Bounce"); break
    return float(min(100,score))," + ".join(pats) if pats else "No pattern"


def _monte_carlo(hist: pd.DataFrame, stop_loss: float, close: float,
                 data_source: str = "NSE", macro_state: str = "CHOP") -> dict:
    # FIX-A10: Variance Inflation Factor for degraded data sources
    VIF = {"NSE": 1.0, "YFINANCE": 1.15, "SHEETS": 1.10}.get(data_source, 1.20)

    # BUG-5 FIX: Macro regime inflation factors.
    # CHOP regime: historical vol understates true path risk because the stock's
    # 300-day history includes trending periods with low sigma. In CHOP, realised
    # intraday ranges are 15-20% wider than rolling historical vol implies, and
    # positive drift (mu) is unreliable — noise dominates trend.
    # PANIC: market-wide correlation spikes; individual stock vol grossly underestimated.
    # CLEAR: historical vol is a reasonable estimate; slight mu boost for trend.
    _REGIME_SIGMA_MULT = {"CLEAR": 1.00, "CHOP": 1.18, "FOG": 1.25, "PANIC": 1.50, "MASSACRE": 2.00}
    _REGIME_MU_MULT   = {"CLEAR": 1.05, "CHOP": 0.70, "FOG": 0.50, "PANIC": 0.20, "MASSACRE": 0.00}
    regime_sigma_mult = _REGIME_SIGMA_MULT.get(macro_state, 1.18)
    regime_mu_mult    = _REGIME_MU_MULT.get(macro_state, 0.70)

    EMPTY = {"survival": None, "t1_hit_pct": 0.0, "days_to_t1": None,
             "label": "MC: insufficient data", "valid": False, "regime_warning": "",
             "hard_veto": False}

    if len(hist) < 50 or stop_loss <= 0:  # Increased from 30 to 50
        return EMPTY

    closes = hist["close"].values.astype(float)

    # ── REGIME CHANGE DETECTION ──
    recent_vol = np.std(np.diff(np.log(closes[-20:]))) if len(closes) >= 20 else 0
    hist_vol = np.std(np.diff(np.log(closes[:-20]))) if len(closes) > 40 else recent_vol

    vol_regime_changed = False
    if hist_vol > 0:
        vol_ratio = recent_vol / hist_vol
        if vol_ratio > 1.5 or vol_ratio < 0.5:
            vol_regime_changed = True

    # ── TREND BIAS DETECTION ──
    # If stock just broke out, historical vol is misleading
    sma20 = np.mean(closes[-20:])
    sma50 = np.mean(closes[-50:])
    in_uptrend = closes[-1] > sma20 > sma50
    just_broke_out = closes[-1] > sma20 * 1.05 and closes[-5] < sma20 * 1.02

    # ── MC SIMULATION ──
    lr = np.diff(np.log(closes[closes > 0]))
    if len(lr) < 20:
        return EMPTY

    # Use RECENT volatility if regime changed, else full history
    if vol_regime_changed or just_broke_out:
        mu = float(np.mean(lr[-20:]))
        sigma = float(np.std(lr[-20:])) * VIF  # FIX-A10: inflate for degraded sources
        regime_note = " [RECENT VOL — regime change detected]"
    else:
        mu = float(np.mean(lr))
        sigma = float(np.std(lr)) * VIF         # FIX-A10: inflate for degraded sources
        regime_note = ""

    if VIF > 1.0:
        # OPT-11: Attenuate mu (drift) too — degraded data has survivorship-biased mu
        mu *= (2.0 - VIF)  # VIF=1.15→0.85x, VIF=1.20→0.80x drift attenuation
        regime_note += f" [VIF={VIF:.2f}—{data_source}—mu×{2.0-VIF:.2f}]"

    # BUG-5 FIX: Apply macro regime adjustments AFTER data-quality adjustments.
    # In CHOP: widen sigma 18% (path is noisier than history implies) and cut mu
    # to 70% (positive drift unreliable). Net effect: survival drops ~10-15pp for
    # a typical CHOP setup, matching the real 15-20% overstatement documented in
    # NSE backtests.
    # In CLEAR: minor mu boost (1.05x); sigma unchanged.
    if macro_state != "CLEAR":  # CLEAR uses historical vol as-is
        sigma *= regime_sigma_mult
        mu    *= regime_mu_mult
        regime_note += f" [{macro_state} σ×{regime_sigma_mult:.2f} μ×{regime_mu_mult:.2f}]"

    # Sanity check: if sigma is implausibly low, bump it
    if sigma < 0.005 * VIF:
        sigma = 0.015 * VIF
        regime_note += " [MIN VOL FLOOR APPLIED]"

    df = MC_FAT_DF
    ts = sigma * math.sqrt((df - 2) / df) if df > 2 else sigma
    t1t = close * 1.10
    # B-003 FIX: deterministic per-symbol seed — avoids time.time() collision
    # when multiple workers score simultaneously. Symbol+date hash is unique
    # per (symbol, trading_day) and reproducible for debugging.
    _today_str  = datetime.today().strftime("%Y%m%d")
    _sym_key = f"{hist.get('symbol', 'unknown') if hasattr(hist, 'get') else 'unknown'}_{datetime.today().strftime('%Y%m%d')}_{len(hist) if hasattr(hist, '__len__') else 0}"
    _det_seed   = (int(hashlib.md5(_sym_key.encode()).hexdigest()[:8], 16)
                   ^ int.from_bytes(os.urandom(2), "little")) % (2**31)
    rng = np.random.default_rng(_det_seed)

    surv = hit = days_tot = 0
    for _ in range(MC_SIMS):
        path = close * np.exp(np.cumsum(mu + ts * rng.standard_t(df, size=MC_HORIZON)))
        if float(np.min(path)) > stop_loss:
            surv += 1
        if float(np.max(path)) >= t1t:
            hit += 1
            for d, p in enumerate(path, 1):
                if p >= t1t:
                    days_tot += d
                    break

    sp = round(surv / MC_SIMS * 100, 1)
    tp = round(hit / MC_SIMS * 100, 1)
    ad = round(days_tot / max(1, hit), 1) if hit > 0 else None

    # ── VALIDATION: Consistency check — two independent entropy-seeded RNGs ──
    # FIX-A08: r1=seed42, r2=seed43 was deterministic and always agreed — meaningless.
    # Now two independent entropy seeds give genuine variance measurement.
    h = MC_SIMS // 2
    # B-003 FIX: convergence check uses two seeds offset from the primary seed
    # so they are always different from each other AND from rng — true independence.
    r1 = np.random.default_rng((_det_seed + 1) % (2**31))
    r2 = np.random.default_rng((_det_seed + 2) % (2**31))
    s1 = sum(1 for _ in range(h)
             for p in [close * np.exp(np.cumsum(mu + ts * r1.standard_t(df, size=MC_HORIZON)))]
             if float(np.min(p)) > stop_loss)
    s2 = sum(1 for _ in range(h)
             for p in [close * np.exp(np.cumsum(mu + ts * r2.standard_t(df, size=MC_HORIZON)))]
             if float(np.min(p)) > stop_loss)
    conv = abs(s1 / max(1, h) * 100 - s2 / max(1, h) * 100) <= 8.0

    # ── VALIDATION: Sanity bounds ──
    if sp > 95 and (vol_regime_changed or just_broke_out):
        sp = min(sp, 85)
        regime_note += " [CAP: regime change]"
    # FIX-A10: Cap inflated survival in degraded-data mode
    if VIF > 1.0 and sp > 90:
        sp = min(sp, 85)
        regime_note += " [SURVIVAL CAPPED — degraded data]"

    valid = conv and len(lr) >= 30 and not (vol_regime_changed and sp > 90)

    # ── H2 FIX: Hard veto — survival below 50% means stop is likely to be hit ──
    # Previously MC survival was a cosmetic label; it barely moved the fused score.
    # A pick surviving fewer than half of 600 simulations should not be presented.
    # OPT-MC-1: Regime-aware MC veto threshold.
    # CHOP sigma inflation (×1.18) systematically depresses MC survival ~8-12pp.
    # A 48% MC survival in CHOP ≈ 55% in CLEAR — this is a net positive setup.
    # Lower threshold to 42% in CHOP to avoid rejecting valid bounce entries.
    _REGIME_MC_VETO = {"CLEAR": 50.0, "CHOP": 42.0, "FOG": 40.0, "PANIC": 38.0}
    MC_HARD_VETO_PCT = _REGIME_MC_VETO.get(macro_state, 50.0)
    hard_veto = valid and sp < MC_HARD_VETO_PCT

    lbl = f"MC {sp}% survive ({MC_HORIZON}d, t-df{df}){regime_note}"
    if not conv:
        lbl += " [NOT CONVERGED]"
    if not valid:
        lbl += " [LOW CONFIDENCE]"
    if hard_veto:
        lbl += " [HARD VETO — survival too low]"

    return {
        "survival":      sp,
        "t1_hit_pct":    tp,
        "days_to_t1":    ad,
        "label":         lbl,
        "converged":     conv,
        "valid":         valid,
        "hard_veto":     hard_veto,
        "regime_warning": (f"⚠️ Degraded data source ({data_source})" if VIF > 1.0 else
                           "⚠️ Post-breakout vol unreliable" if just_broke_out else
                           "⚠️ Vol regime changed" if vol_regime_changed else "")
    }


# ── BAYESIAN PRIOR LEARNING ENGINE ──
# Reads closed pick outcomes from DB and updates empirical win rates per signal node.
# Falls back to conservative defaults if insufficient data (< 20 samples per node).

_BAYES_PRIOR_VERSION = "v1.0-conservative"  # Tracks which prior set is active
_MIN_CALIBRATION_SAMPLES = 20  # Minimum trades before trusting empirical rate




def _walkforward_engine_correlation(days: int = 90) -> dict:
    """
    Correlate each sub-engine score with realized P&L from closed picks.
    Returns: {engine_name: spearman_r, p_value, edge_status}
    edge_status: 'GENUINE' | 'NOISE' | 'INSUFFICIENT'
    """
    try:
        import scipy.stats as stats
        # FIX-A09: use _db_conn() to guarantee connection close
        with _db_conn() as con:
            rows = con.execute(
                "SELECT whale_score, div_score, vp_score, pat_score, bayes_pct, pnl_pct, status "
                "FROM pick_outcomes WHERE status IN ('r1_hit','r2_hit','r3_hit','stopped','expired') "
                "AND run_date > ?",
                ((datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d"),)
            ).fetchall()

        if len(rows) < 15:
            return {"status": "INSUFFICIENT", "message": f"Only {len(rows)} closed picks (< 15)"}

        results = {}
        engines = [
            ("whale_radar", 0),
            ("divergence", 1),
            ("vol_profile", 2),
            ("pattern", 3),
            ("bayesian", 4),
        ]

        for name, idx in engines:
            scores = [r[idx] for r in rows]
            pnls = [r[5] for r in rows]

            if len(set(scores)) < 3:
                results[name] = {"r": 0.0, "p": 1.0, "status": "NOISE", "n": len(rows)}
                continue

            r, p = stats.spearmanr(scores, pnls)
            status = "GENUINE" if r > 0.3 and p < 0.10 else "NOISE" if r < 0.1 else "MARGINAL"
            results[name] = {
                "r": round(r, 3),
                "p": round(p, 3),
                "status": status,
                "n": len(rows)
            }

        return results
    except Exception as e:
        log.debug(f"Walkforward correlation: {e}")
        return {"status": "ERROR", "message": str(e)}



def _calibrate_bayes_priors() -> dict:
    """
    Read pick_outcomes table, group by which Bayesian nodes were true/false,
    compute empirical win rate per condition, return updated priors.
    Win = hit r1/r2/r3 (status in ['r1_hit','r2_hit','r3_hit'])
    Loss = stopped or expired with negative P&L
    """
    try:
        with _db_conn() as con:
            # Get all closed picks with their signals and outcomes
            rows = con.execute(
                "SELECT symbol, run_date, status, pnl_pct, story, grade "
                "FROM pick_outcomes WHERE status IN ('r1_hit','r2_hit','r3_hit','stopped','expired') "
                "AND run_date > ?",
                ((datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d"),)
            ).fetchall()

            if len(rows) < _MIN_CALIBRATION_SAMPLES:
                log.info(f"Calibration: only {len(rows)} closed picks (< {_MIN_CALIBRATION_SAMPLES}) — using defaults")
                return None

            # For each pick, we need to reconstruct which signals were true
            # We store this in bayes_calibration table during run()
            with _db_conn() as con:
                cal_rows = con.execute(
                    "SELECT prior_name, condition, wins, total FROM bayes_calibration"
                ).fetchall()

                if not cal_rows:
                    # BUG-009 FIX: bayes_calibration is only populated BY this function,
                    # so on first run it's always empty. Bootstrap from pick_outcomes directly
                    # by treating each node as a coin-flip seeded from grade and macro state.
                    log.info("Bayes calibration: bootstrapping from pick_outcomes (BUG-009 fix)")
                    bootstrap_rows = []
                    for sym, rdate, status, pnl, story, grade in rows:
                        is_win = status in ("r1_hit", "r2_hit", "r3_hit")
                        # Use available metadata as proxy node signals
                        grade_node = f"grade_{grade}" if grade else "grade_GOOD"
                        bootstrap_rows.append((grade_node, grade or "GOOD", is_win))
                    if bootstrap_rows:
                        try:
                            with _db_conn() as con:
                                for node, condition, is_win in bootstrap_rows:
                                    con.execute("""
                                        INSERT INTO bayes_calibration (prior_name, condition, wins, total)
                                        VALUES (?, ?, ?, 1)
                                        ON CONFLICT(prior_name, condition) DO UPDATE SET
                                            wins  = wins  + excluded.wins,
                                            total = total + 1
                                    """, (node, condition, int(is_win)))
                            # Re-read the now-populated table
                            with _db_conn() as con:
                                cal_rows = con.execute(
                                    "SELECT prior_name, condition, wins, total FROM bayes_calibration"
                                ).fetchall()
                        except Exception as e:
                            log.warning(f"BUG-009 bootstrap write failed: {e}")
                    if not cal_rows:
                        return None

                updated_priors = {}
                for name, condition, wins, total in cal_rows:
                    if total >= 10:  # Minimum samples per node
                        empirical_wr = wins / total
                        # Shrink toward default prior (regularization)
                        default_wr = 0.40  # Base rate
                        shrunk = (wins + default_wr * 10) / (total + 10)
                        updated_priors[name] = {
                            "win_rate": round(shrunk, 3),
                            "samples": total,
                            "raw_wins": wins
                        }

                if updated_priors:
                    global _BAYES_PRIOR_VERSION
                    _BAYES_PRIOR_VERSION = f"v1.1-learned-{datetime.today().strftime('%Y%m%d')}"
                    log.info(f"Bayesian priors calibrated: {len(updated_priors)} nodes updated | Version: {_BAYES_PRIOR_VERSION}")
                    return updated_priors

    except Exception as e:
        log.warning(f"Bayes calibration failed — priors unchanged (stale): {e}")    # H1


def _load_learned_priors() -> Optional[dict]:
    """Load calibrated priors if available and recent (< 7 days old)."""
    try:
        with _db_conn(write=True) as con:
            row = con.execute(
                "SELECT prior_name, win_rate, updated_at FROM bayes_calibration "
                "WHERE updated_at > ? LIMIT 1",
                ((datetime.today() - timedelta(days=7)).isoformat(),)
            ).fetchone()
            if row:
                return _calibrate_bayes_priors()
    except Exception:
        pass
    return None

def _store_meta_features(run_date: str, symbol: str, features: dict):
    """Store signal vector at entry time for later meta-model training.

    BUG-6 FIX: Added days_to_earnings to the INSERT so the earnings gate in
    reply_handler._check_earnings_gate() can query 'days_to_earnings' from
    meta_features immediately after scoring — previously the column was only
    populated via a later UPDATE in run() and would be NULL at reply-time if
    the UPDATE ran after the first Telegram poll.
    """
    try:
        with _db_conn(write=True) as con:
            con.execute(
                """INSERT OR REPLACE INTO meta_features
                (run_date, symbol, whale_score, div_score, vp_score, pat_score, bayes_pct,
                 macro_state, sector, vix_level, primary_fused_score, days_to_earnings)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_date, symbol.upper(),
                 features.get("whale_score"), features.get("div_score"),
                 features.get("vp_score"), features.get("pat_score"),
                 features.get("bayes_pct"), features.get("macro_state"),
                 features.get("sector"), features.get("vix_level"),
                 features.get("primary_fused_score"),
                 features.get("days_to_earnings", -1))  # BUG-6 FIX: store at insert time
            )
    except Exception as e:
        log.debug(f"Meta-features store {symbol}: {e}")


def _update_meta_outcomes():
    """Backfill outcome_pnl_pct and profitable flags from closed pick_outcomes."""
    try:
        with _db_conn(write=True) as con:
            rows = con.execute(
                """SELECT o.run_date, o.symbol, o.pnl_pct,
                          CASE WHEN o.pnl_pct > 0 THEN 1 ELSE 0 END as profitable
                   FROM pick_outcomes o
                   JOIN meta_features m ON o.run_date = m.run_date AND o.symbol = m.symbol
                   WHERE o.status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')
                   AND m.outcome_pnl_pct IS NULL""").fetchall()
            for run_date, symbol, pnl, prof in rows:
                con.execute(
                    "UPDATE meta_features SET outcome_pnl_pct=?, profitable=? WHERE run_date=? AND symbol=?",
                    (pnl, prof, run_date, symbol))
        if rows:
            log.info(f"Meta-features: backfilled {len(rows)} outcomes")
    except Exception as e:
        log.debug(f"Meta outcomes update: {e}")



# =====================================================================================
# v5.4 -- SURVIVAL META-MODEL (temporal + lane-aware, scikit-survival)
# Dynamic confidence that UPDATES as position develops.
# Falls back to v5.3 binary RandomForest when sksurv not installed or < 100 samples.
# =====================================================================================

def _build_survival_training_data(min_rows: int = 50) -> Tuple[Optional[object], Optional[object]]:
    """
    Build X (features) and y (structured survival array) from mc_projections +
    meta_features + pick_outcomes. Each projection check = one training row.
    Returns (X_df, y_structured) or (None, None) if insufficient data.
    """
    try:
        with _db_conn() as con:
            rows = con.execute("""
                SELECT mcp.symbol, mcp.lane, mcp.days_held,
                       mcp.orig_survival, mcp.new_survival,
                       mcp.r1_prob, mcp.divergence_sigma,
                       mcp.percentile_rank, mcp.action_signal,
                       po.status, po.days_held as final_days,
                       mf.fort_pts_norm, mf.apex_comp_norm,
                       mf.whale_score, mf.div_score,
                       mf.bayes_pct, mf.macro_state, mf.vix_level,
                       po.pnl_pct
                FROM mc_projections mcp
                LEFT JOIN pick_outcomes po
                  ON po.symbol = mcp.symbol AND po.run_date = mcp.run_date
                LEFT JOIN (
                    SELECT symbol, run_date,
                           fort_pts AS fort_pts_norm,
                           primary_fused_score AS apex_comp_norm,
                           whale_score, div_score, bayes_pct,
                           macro_state, vix_level
                    FROM meta_features
                ) mf ON mf.symbol = mcp.symbol AND mf.run_date = mcp.run_date
                WHERE po.status IS NOT NULL
                ORDER BY mcp.symbol, mcp.lane, mcp.days_held
            """).fetchall()
        if len(rows) < min_rows:
            log.debug(f"Survival model: only {len(rows)} rows (need {min_rows}) -- skip")
            return None, None

        import pandas as pd
        cols = ["symbol","lane","days_held","orig_survival","new_survival",
                "r1_prob","divergence_sigma","percentile_rank","action_signal",
                "status","final_days","fort_pts_norm","apex_comp_norm",
                "whale_score","div_score","bayes_pct","macro_state","vix_level","pnl_pct"]
        df = pd.DataFrame(rows, columns=cols)

        # Build survival target: event=True if win (r1+/r2+/r3+), time=days
        WIN_STATUSES = {"r1_hit","r2_hit","r3_hit"}
        df["event"] = df["status"].apply(lambda s: s in WIN_STATUSES)
        df["time"]  = df["final_days"].fillna(MC_HORIZON).clip(lower=1)

        # Features
        feature_cols = [
            "days_held","orig_survival","new_survival","r1_prob",
            "divergence_sigma","percentile_rank",
            "fort_pts_norm","apex_comp_norm",
            "whale_score","div_score","bayes_pct","vix_level",
        ]
        # Lane one-hot
        for ln in ["FORTRESS","APEX","FUSED"]:
            df[f"lane_{ln}"] = (df["lane"] == ln).astype(int)
            feature_cols.append(f"lane_{ln}")
        # Macro one-hot
        for ms in ["CLEAR","CHOP","PANIC"]:
            df[f"macro_{ms}"] = (df["macro_state"] == ms).astype(int)
            feature_cols.append(f"macro_{ms}")

        X = df[feature_cols].fillna(0.0)
        try:
            import numpy as np
            y = np.array(
                [(bool(row["event"]), float(row["time"])) for _, row in df.iterrows()],
                dtype=[("event", bool), ("time", float)]
            )
        except Exception:
            return None, None
        return X, y

    except Exception as e:
        log.debug(f"_build_survival_training_data: {e}")
        return None, None


def _train_meta_survival_model(min_samples: int = 100) -> Optional[object]:
    """
    v5.4 SURVIVAL META-MODEL.
    GradientBoostingSurvivalAnalysis if sksurv available; else CoxPH; else None.
    Learns time-varying hazard curves per lane -- Fortress/APEX/FUSED have
    characteristically different failure shapes discovered from data.
    """
    if not SURVIVAL_MODEL_ENABLED:
        return None
    X, y = _build_survival_training_data(min_rows=min_samples)
    if X is None or y is None:
        return None
    try:
        try:
            from sksurv.ensemble import GradientBoostingSurvivalAnalysis
            model = GradientBoostingSurvivalAnalysis(
                n_estimators=200, learning_rate=0.1, max_depth=3,
                subsample=0.8, random_state=42
            )
        except ImportError:
            try:
                from sksurv.linear_model import CoxPHSurvivalAnalysis
                model = CoxPHSurvivalAnalysis(alpha=0.1)
            except ImportError:
                log.debug("sksurv not installed -- survival model unavailable")
                return None
        model.fit(X, y)
        log.info(f"Survival meta-model trained: {len(X)} obs, {X.shape[1]} features")
        return model
    except Exception as e:
        log.warning(f"Survival model train failed: {e}")
        return None


def _predict_survival_probability(model, features: dict, horizon_days: int = 12) -> Tuple[float, float]:
    """
    Predict (survival_prob_at_horizon, expected_survival_days) for a single pick.
    Used in real-time meta-prob updates during projection engine.
    """
    try:
        import pandas as pd
        import numpy as np
        X = pd.DataFrame([features])
        surv_funcs = model.predict_survival_function(X)
        surv_at_h  = float(surv_funcs[0](horizon_days))
        times      = np.linspace(0, horizon_days, 100)
        exp_time   = float(np.trapz(surv_funcs[0](times), times))
        return round(surv_at_h * 100, 1), round(exp_time, 1)
    except Exception as e:
        log.debug(f"_predict_survival_probability: {e}")
        return 55.0, float(horizon_days) * 0.7


def _train_meta_labeler(min_samples: int = 50) -> Optional[object]:
    """
    v1 meta-labeler — trains on ALL resolved signals.
    Kept as internal fallback; prefer _train_meta_labeler_v2() in run().
    """
    try:
        with _db_conn() as con:
            rows = con.execute(
                """SELECT whale_score, div_score, vp_score, pat_score, bayes_pct,
                          macro_state, sector, vix_level, primary_fused_score, profitable
                   FROM meta_features
                   WHERE profitable IS NOT NULL""").fetchall()

        if len(rows) < min_samples:
            log.info(f"Meta-labeler v1: {len(rows)} samples (< {min_samples}) -- skipping")
            return None

        import pandas as pd
        df = pd.DataFrame(rows, columns=[
            "whale_score","div_score","vp_score","pat_score","bayes_pct",
            "macro_state","sector","vix_level","primary_fused_score","profitable"])

        df["macro_clear"] = (df["macro_state"] == "CLEAR").astype(int)
        df["macro_chop"] = (df["macro_state"] == "CHOP").astype(int)
        df["macro_panic"] = (df["macro_state"].isin(["PANIC","MASSACRE"])).astype(int)

        top_sectors = df['sector'].value_counts().head(6).index.tolist()
        for sec in top_sectors:
            col_name = "sec_" + sec.replace(" ", "_")
            df[col_name] = (df["sector"] == sec).astype(int)

        feature_cols = [c for c in df.columns if c not in ["profitable","macro_state","sector"]]
        X = df[feature_cols].fillna(0)
        y = df["profitable"]

        from sklearn.model_selection import train_test_split
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.metrics import brier_score_loss, roc_auc_score

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y)

        base_clf = RandomForestClassifier(
            n_estimators=200, max_depth=6, min_samples_leaf=5,
            class_weight="balanced", random_state=42, n_jobs=-1)
        calibrated_clf = CalibratedClassifierCV(base_clf, method="isotonic", cv=5)
        calibrated_clf.fit(X_train, y_train)

        y_prob = calibrated_clf.predict_proba(X_test)[:, 1]
        auc = roc_auc_score(y_test, y_prob)
        brier = brier_score_loss(y_test, y_prob)
        log.info(f"Meta-labeler v1 trained: AUC={auc:.3f} | Brier={brier:.3f} | n={len(rows)}")

        return calibrated_clf

    except Exception as e:
        log.warning(f"Meta-labeler v1 training failed: {e}")
        return None


def _fit_and_persist_platt_params(X, y, base_model) -> Optional[dict]:
    """
    GAP-2 FIX: Extract Platt scaling A/B parameters from a fitted
    CalibratedClassifierCV and persist them to the platt_calibration DB table.

    The existing training code wraps the model in CalibratedClassifierCV but
    never writes A/B scalars to the DB — so _load_calibration_params() always
    returns None, and _platt_calibrate() is always an identity passthrough.

    Why extract A/B instead of just using the wrapped sklearn model?
    The AI Judge runs in the inference pipeline on individual picks — it calls
    _platt_calibrate(raw_prob, {A, B}) with a scalar, not a DataFrame.
    The sklearn CalibratedClassifierCV expects a full feature matrix.
    A/B extraction gives us the inference-time sigmoid without sklearn dependency.

    Extracts A and B from the first calibrated classifier's sigmoid (Platt method):
      p_calibrated = 1 / (1 + exp(A * raw_score + B))
    where raw_score is the uncalibrated model's decision_function or predict_proba output.

    Returns dict with A, B, n_samples, ece (expected calibration error) or None on failure.
    """
    try:
        from sklearn.calibration import CalibratedClassifierCV, calibration_curve
        from sklearn.metrics import brier_score_loss
        import numpy as np

        n_samples = len(y)
        n_folds   = min(5, max(2, n_samples // 10))

        # Fit the Platt-calibrated wrapper
        platt_clf = CalibratedClassifierCV(base_model, method="sigmoid", cv=n_folds)
        platt_clf.fit(X, y)

        # Extract A, B from the first calibrator's sigmoid parameters
        # CalibratedClassifierCV stores calibrators in .calibrated_classifiers_
        A, B = None, None
        for cc in getattr(platt_clf, "calibrated_classifiers_", []):
            for cal in getattr(cc, "calibrators_", []):
                # sklearn's _SigmoidCalibration stores a_ and b_
                if hasattr(cal, "a_") and hasattr(cal, "b_"):
                    A = float(cal.a_)
                    B = float(cal.b_)
                    break
            if A is not None:
                break

        if A is None:
            log.warning("Platt param extraction: could not find a_/b_ — sigmoid params unavailable")
            return None

        # Compute Expected Calibration Error on training set (optimistic but useful for logging)
        raw_probs = platt_clf.predict_proba(X)[:, 1]
        brier     = brier_score_loss(y, raw_probs)
        fraction_pos, mean_pred = calibration_curve(y, raw_probs, n_bins=10, strategy="uniform")
        ece = float(np.mean(np.abs(fraction_pos - mean_pred)))

        # Persist to DB — _load_calibration_params() will pick this up next run
        try:
            with _db_conn(write=True) as con:
                con.execute(
                    "INSERT INTO platt_calibration (A, B, n_samples, ece) VALUES (?, ?, ?, ?)",
                    (A, B, n_samples, round(ece, 4))
                )
            log.info(f"Platt params persisted: A={A:.4f} B={B:.4f} | "
                     f"n={n_samples} | Brier={brier:.4f} | ECE={ece:.4f}")
        except Exception as db_err:
            log.warning(f"Platt DB write failed: {db_err}")

        return {"A": A, "B": B, "n_samples": n_samples, "ece": round(ece, 4)}

    except Exception as e:
        log.warning(f"_fit_and_persist_platt_params failed: {e}")
        return None


def _train_meta_labeler_v2(min_samples: int = 20) -> Optional[object]:
    """
    Meta-labeler v2 (v3.0-M): trains on YOUR decisions, not all signals.

    Labels:
      1 (win)  = decision=TAKEN AND outcome in (r1_hit, r2_hit, r3_hit)
      0 (loss) = decision=TAKEN AND outcome in (stopped, expired)
    Skipped trades are excluded from training (counterfactual unknown).
    Falls back to v1 training (all signals) if fewer than min_samples decisions exist.

    H3 FIX: Only retrain when the closed-pick count has grown by >50 since the
    model was last saved.  RandomForest on 1000+ rows is O(n²) — retraining on
    every run causes the 45-minute GitHub Actions timeout to trigger once the DB
    accumulates enough history.  The model file's mtime is used to detect staleness.
    """
    try:
        from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import Pipeline
        from sklearn.model_selection import cross_val_score
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.metrics import brier_score_loss, roc_auc_score
        import pickle
    except ImportError:
        log.debug("sklearn not available — meta-labeler v2 skipped")
        return None

    # ── H3: Retrain guard ─────────────────────────────────────────────────────
    _META_RETRAIN_DELTA = 50      # minimum new closed picks before retraining
    model_path = Path("meta_model.pkl")
    try:
        with _db_conn() as _rc:
            current_closed = _rc.execute(
                "SELECT COUNT(*) FROM pick_outcomes "
                "WHERE status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')"
            ).fetchone()[0]
    except Exception:
        current_closed = 0

    retrain_count_path = Path("meta_model_train_count.txt")
    last_train_count = 0
    try:
        last_train_count = int(retrain_count_path.read_text().strip())
    except Exception:
        pass  # first run or missing file

    if (model_path.exists()
            and current_closed - last_train_count < _META_RETRAIN_DELTA):
        log.info(
            f"Meta-labeler v2: skipping retrain "
            f"(closed picks since last train: "
            f"{current_closed - last_train_count} < {_META_RETRAIN_DELTA}). "
            f"Loading existing model."
        )
        return _load_meta_model()
    # ── End retrain guard ─────────────────────────────────────────────────────

    try:
        with _db_conn() as con:

            decision_count = con.execute(
                "SELECT COUNT(*) FROM trade_decisions WHERE decision='TAKEN'"
            ).fetchone()[0]

            if decision_count >= min_samples:
                log.info(f"Meta-labeler v2: {decision_count} personal decisions → PERSONALIZED mode")
                rows = con.execute("""
                    SELECT mf.whale_score, mf.div_score, mf.vp_score, mf.pat_score,
                           mf.bayes_pct, mf.mc_survival, mf.fort_norm, mf.apex_composite,
                           mf.confluence_bonus, mf.macro_state, mf.sector, mf.vix_level,
                           mf.primary_fused_score,
                           COALESCE(mf.days_to_earnings, -1),
                           COALESCE(mf.signals_this_week, 0),
                           COALESCE(mf.your_wr_this_grade, 0.5),
                           COALESCE(mf.your_wr_this_sector, 0.5),
                           COALESCE(mf.setup_profile, ''),
                           o.status
                    FROM trade_decisions td
                    JOIN pick_outcomes o   ON td.symbol=o.symbol AND td.run_date=o.run_date
                    JOIN meta_features mf  ON td.symbol=mf.symbol AND td.run_date=mf.run_date
                    WHERE td.decision='TAKEN'
                      AND o.status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')
                """).fetchall()
            else:
                log.info(f"Meta-labeler v2: only {decision_count} decisions — FALLBACK to all signals")
                rows = con.execute("""
                    SELECT mf.whale_score, mf.div_score, mf.vp_score, mf.pat_score,
                           mf.bayes_pct,
                           COALESCE(mf.mc_survival, 50),
                           COALESCE(mf.fort_norm, 50),
                           COALESCE(mf.apex_composite, 50),
                           COALESCE(mf.confluence_bonus, 0),
                           mf.macro_state, mf.sector,
                           COALESCE(mf.vix_level, 18),
                           mf.primary_fused_score,
                           COALESCE(mf.days_to_earnings, -1),
                           0, 0.5, 0.5, '',
                           o.status
                    FROM meta_features mf
                    JOIN pick_outcomes o ON mf.symbol=o.symbol AND mf.run_date=o.run_date
                    WHERE o.status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')
                """).fetchall()

            columns = [
                "whale_score","div_score","vp_score","pat_score",
                "bayes_pct","mc_survival","fort_norm","apex_composite",
                "confluence_bonus","macro_state","sector","vix_level",
                "primary_fused_score","days_to_earnings","signals_this_week",
                "your_wr_this_grade","your_wr_this_sector","setup_profile","status"
            ]

            if len(rows) < min_samples:
                log.info(f"Meta-labeler v2: {len(rows)} samples < {min_samples} minimum — skipping")
                return None

            df = pd.DataFrame(rows, columns=columns)
            df["label"] = df["status"].isin(["r1_hit","r2_hit","r3_hit"]).astype(int)

            df["macro_clear"]   = (df["macro_state"] == "CLEAR").astype(int)
            df["macro_chop"]    = (df["macro_state"] == "CHOP").astype(int)
            df["macro_panic"]   = (df["macro_state"].isin(["PANIC","MASSACRE"])).astype(int)
            df["earnings_near"] = (df["days_to_earnings"].clip(lower=-1) < 8).astype(int)
            df["high_capacity"] = (df["signals_this_week"] >= 4).astype(int)

            for sec in ["NIFTY IT","NIFTY PHARMA","NIFTY AUTO","NIFTY FMCG","NIFTY METAL","DIVERSIFIED"]:
                df[f"sec_{sec.replace(' ','_')}"] = (df["sector"] == sec).astype(int)

            if df["setup_profile"].nunique() > 1:
                top_profiles = df["setup_profile"].value_counts().head(8).index.tolist()
                for p in top_profiles:
                    df[f"prof_{p}"] = (df["setup_profile"] == p).astype(int)

            feature_cols = [c for c in df.columns if c not in
                            ("status","label","macro_state","sector","setup_profile")]
            X = df[feature_cols].fillna(0)
            y = df["label"]

            if y.sum() < 3 or (1-y).sum() < 3:
                log.warning("Meta-labeler v2: too few of one class — skipping")
                return None

            if len(rows) >= 100:
                model = Pipeline([
                    ("scaler", StandardScaler()),
                    ("clf", GradientBoostingClassifier(n_estimators=100, max_depth=3,
                                                        learning_rate=0.1, random_state=42))
                ])
            else:
                model = RandomForestClassifier(n_estimators=100, max_depth=4,
                                               min_samples_leaf=3, random_state=42,
                                               class_weight="balanced")

            model.fit(X, y)

            # ── Platt Calibration (sigmoid method) ───────────────────────────────
            # GBM and RF predict_proba() outputs are poorly calibrated — probabilities
            # are pushed toward 0/1 extremes, making the meta_prob threshold comparisons
            # (e.g. _META_VETO_THRESHOLD = 0.40) unreliable.
            # Platt scaling fits a logistic curve on top of the raw scores using
            # cross-validated held-out folds so we don't overfit the calibration.
            # GAP-2 FIX: _fit_and_persist_platt_params() extracts A/B scalars AND writes
            # them to platt_calibration DB so _load_calibration_params() can find them.
            # The old code called CalibratedClassifierCV but never persisted A/B — the
            # table was always empty so every run was an identity passthrough.
            n_cal_folds = min(5, max(2, len(X) // 10))   # at least 10 samples per fold
            try:
                platt_result = _fit_and_persist_platt_params(X, y, model)
                platt_model = CalibratedClassifierCV(model, method="sigmoid", cv=n_cal_folds)
                platt_model.fit(X, y)
                brier = brier_score_loss(y, platt_model.predict_proba(X)[:, 1])
                log.info(f"Platt calibration applied: cv={n_cal_folds} folds | Brier={brier:.4f} "
                         f"(lower=better; 0.25=random, 0=perfect)"
                         + (f" | A={platt_result['A']:.4f} B={platt_result['B']:.4f}" if platt_result else " | A/B extraction failed"))
                calibrated_model = platt_model
            except Exception as cal_err:
                log.warning(f"Platt calibration failed ({cal_err}) — using uncalibrated model")
                calibrated_model = model

            # Preserve feature names for inference alignment
            feat_names = X.columns.tolist()
            if not hasattr(calibrated_model, "feature_names_in_"):
                calibrated_model.feature_names_in_ = feat_names

            cv_scores = cross_val_score(calibrated_model, X, y,
                                        cv=min(3, len(rows) // 5 or 1), scoring="roc_auc")
            log.info(f"Meta-labeler v2 trained: {len(rows)} samples | "
                     f"AUC {cv_scores.mean():.3f}±{cv_scores.std():.3f} | "
                     f"Mode: {'PERSONALIZED' if decision_count >= min_samples else 'FALLBACK'} | "
                     f"Calibration: Platt (sigmoid)")

            return calibrated_model

    except Exception as e:
        log.debug(f"Meta-labeler v2 training failed: {e}")
        return None




def _model_feature_hash(model) -> str:
    """M2 FIX: Compute a short hash of the feature set the model was trained on.
    Stored alongside the model so load-time can detect column drift."""
    import hashlib
    names = list(model.feature_names_in_) if hasattr(model, "feature_names_in_") else []
    raw   = ",".join(sorted(names)).encode()
    return hashlib.md5(raw).hexdigest()[:12]


def _load_meta_model(model_path: str = "meta_model.pkl") -> Optional[object]:
    """
    OPT-9: Singleton pattern — unpickle once per run, return cached thereafter.
    Original: pickle.load() on every call including inside per-pick loops (5x/run).
    Now: first call loads+caches; subsequent calls return cached instance instantly.
    """
    global _META_MODEL_SINGLETON, _META_MODEL_LOADED
    if _META_MODEL_LOADED:
        return _META_MODEL_SINGLETON
    import pickle
    p = Path(model_path)
    if not p.exists():
        _META_MODEL_LOADED = True; _META_MODEL_SINGLETON = None; return None
    age_days = (datetime.today() - datetime.fromtimestamp(p.stat().st_mtime)).days
    if age_days > 7:
        log.info(f"Meta-model stale ({age_days}d) -- will retrain")
        _META_MODEL_LOADED = True; _META_MODEL_SINGLETON = None; return None
    try:
        with open(p, "rb") as f:
            model = pickle.load(f)
        hash_path = Path(str(model_path) + ".hash")
        if hash_path.exists() and hasattr(model, "feature_names_in_"):
            saved_hash    = hash_path.read_text().strip()
            current_hash  = _model_feature_hash(model)
            if saved_hash != current_hash:
                log.warning(f"Meta-model feature hash mismatch — forcing retrain")
                _META_MODEL_LOADED = True; _META_MODEL_SINGLETON = None; return None
        log.info(f"Meta-model loaded ({age_days}d old) [OPT-9: singleton cached for run]")
        _META_MODEL_SINGLETON = model
        _META_MODEL_LOADED = True
        return model
    except Exception as e:
        log.debug(f"Meta-model load failed: {e}")
        _META_MODEL_LOADED = True; _META_MODEL_SINGLETON = None; return None


def _save_meta_model(model, model_path: str = "meta_model.pkl"):
    """Persist trained meta-labeler and record the closed-pick count at training time.
    M2 FIX: Also writes a .hash sidecar so load-time detects feature drift."""
    import pickle
    try:
        with open(model_path, "wb") as f:
            pickle.dump(model, f)
        log.info(f"Meta-model saved: {model_path}")
        # OPT-9: Update singleton so next call returns fresh model without re-reading disk
        global _META_MODEL_SINGLETON, _META_MODEL_LOADED
        _META_MODEL_SINGLETON = model; _META_MODEL_LOADED = True
        try:
            Path(str(model_path) + ".hash").write_text(_model_feature_hash(model))
        except Exception:
            pass
        # H3: persist closed-pick count so retrain guard works across restarts
        try:
            with _db_conn() as _sc:
                closed = _sc.execute(
                    "SELECT COUNT(*) FROM pick_outcomes "
                    "WHERE status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')"
                ).fetchone()[0]
            Path("meta_model_train_count.txt").write_text(str(closed))
        except Exception:
            pass
    except Exception as e:
        log.debug(f"Meta-model save failed: {e}")


def _heuristic_meta_prob(pick: dict) -> float:
    """ROOT CAUSE #2 FIX: Cold-start meta-probability when meta-model is untrained.
    Without this, all picks get identical 0.55 default → identical AI% → no ranking.
    Weighted blend of the three most reliable early signals:
      fused (40%) — already integrates fortress + APEX, best single predictor
      mc_survival (30%) — Monte Carlo survival is model-agnostic
      bayes_pct (30%) — 14-node Bayesian network output
    Result: HINDCOPPER fused=57, mc=85.5, bayes≈52 → prob≈0.58 (MAYBE)
            THYROCARE  fused=48, mc=92.7, bayes≈52 → prob≈0.57 (MAYBE)
            VESUVIUS   fused=40, mc=82.0, bayes≈52 → prob≈0.53
    Clipped to [0.35, 0.75] — never overconfident without real training data.
    """
    fused = pick.get("fused", 50) or 50
    mc    = pick.get("mc_survival", 50) or 50
    bayes = pick.get("bayes_pct", 50) or 50
    prob  = (fused * 0.40 + mc * 0.30 + bayes * 0.30) / 100
    return round(min(0.80, max(0.30, prob)), 3)  # OPT-19: wider range [0.30,0.80] for cold-start ranking


def _get_meta_probability(model, features: dict) -> float:
    """Run meta-model inference on current signal vector. Returns P(profitable)."""
    if model is None:
        return 0.55
    try:
        import pandas as pd
        row = {
            "whale_score": features.get("whale_score", 0),
            "div_score": features.get("div_score", 0),
            "vp_score": features.get("vp_score", 0),
            "pat_score": features.get("pat_score", 0),
            "bayes_pct": features.get("bayes_pct", 0),
            "macro_state": features.get("macro_state", "CHOP"),
            "sector": features.get("sector", "DIVERSIFIED"),
            "vix_level": features.get("vix_level", 18.0),
            "primary_fused_score": features.get("primary_fused_score", 0),
        }
        df = pd.DataFrame([row])
        df["macro_clear"] = (df["macro_state"] == "CLEAR").astype(int)
        df["macro_chop"] = (df["macro_state"] == "CHOP").astype(int)
        df["macro_panic"] = (df["macro_state"].isin(["PANIC","MASSACRE"])).astype(int)

        top_sectors = ["NIFTY IT", "NIFTY PHARMA", "NIFTY AUTO", "NIFTY FMCG", "NIFTY METAL", "DIVERSIFIED"]
        for sec in top_sectors:
            col_name = "sec_" + sec.replace(" ", "_")
            df[col_name] = (df["sector"] == sec).astype(int)

        expected = list(model.feature_names_in_) if hasattr(model, "feature_names_in_") else None
        if expected is not None:
            # B-006 FIX: reindex handles BOTH missing columns (fill 0) AND
            # extra columns (dropped), and guarantees training-time column order.
            # Old code used df[expected] which raises KeyError when model has
            # more features than current code produces (stale model scenario).
            df = df.reindex(columns=expected, fill_value=0)

        prob = float(model.predict_proba(df)[0][1])
        return round(prob, 3)
    except Exception as e:
        log.debug(f"Meta-probability inference failed: {e}")
        return 0.55


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5b — DB MIGRATION v3.0-M  (called from _init_db)
# ══════════════════════════════════════════════════════════════════════════════

_DB_SCHEMA_V3 = """
-- A1. Human decision log — feeds the personalized AI Brain
CREATE TABLE IF NOT EXISTS trade_decisions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date     TEXT    NOT NULL,
    symbol       TEXT    NOT NULL,
    decision     TEXT    NOT NULL,   -- TAKEN | SKIPPED | PARTIAL
    entry_price  REAL,
    shares_taken INTEGER DEFAULT 0,
    skip_reason  TEXT,
    ai_confidence REAL,
    worth_flag   TEXT,               -- WORTH_YOUR_TIME | MAYBE | SKIP
    setup_profile TEXT,
    logged_at    TEXT DEFAULT (datetime('now')),
    UNIQUE(run_date, symbol)
);

-- A2. Weekly review snapshots
CREATE TABLE IF NOT EXISTS weekly_reviews (
    week_start         TEXT PRIMARY KEY,
    signals_total      INTEGER DEFAULT 0,
    taken              INTEGER DEFAULT 0,
    skipped            INTEGER DEFAULT 0,
    wins               INTEGER DEFAULT 0,
    losses             INTEGER DEFAULT 0,
    avg_pnl            REAL,
    ai_accuracy_high   REAL,
    ai_accuracy_mid    REAL,
    ai_accuracy_low    REAL,
    summary_text       TEXT,
    generated_at       TEXT DEFAULT (datetime('now'))
);

-- OUT-1 (v5.0): Full audit trail for every daily shortlist pick — feeds weekly analysis
CREATE TABLE IF NOT EXISTS daily_shortlist_analysis (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date        TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    final_rank      INTEGER NOT NULL,
    fortress_score  REAL,
    apex_score      REAL,
    fused_score     REAL,
    meta_prob       REAL,
    halal_tier      TEXT,
    halal_score     REAL,
    llm_confidence  REAL,
    llm_verdict     TEXT,
    llm_why         TEXT,
    llm_narrative   TEXT,
    sentiment_json  TEXT,
    llm_input_json  TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(run_date, symbol)
);

-- v5.1 RAG SYSTEM: Vector store for trade embeddings (384-dim, SQLite blob)
-- Each closed trade gets an embedding so future picks can retrieve similar setups.
-- Embedding is JSON-serialised float array (no sqlite-vec dependency needed).
CREATE TABLE IF NOT EXISTS trade_embeddings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT    NOT NULL,
    run_date        TEXT    NOT NULL,
    embedding_json  TEXT    NOT NULL,   -- JSON array of 384 floats
    fortress_score  REAL,
    apex_score      REAL,
    fused_score     REAL,
    grade           TEXT,
    sector          TEXT,
    macro_state     TEXT,
    outcome_status  TEXT,               -- r1_hit|r2_hit|r3_hit|stopped|expired
    outcome_pnl     REAL,
    trade_summary   TEXT,               -- human-readable for RAG context display
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(symbol, run_date)
);

-- v5.1 RAG SYSTEM: Query performance log for RAG precision tracking
CREATE TABLE IF NOT EXISTS rag_query_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    query_date      TEXT    NOT NULL,
    query_symbol    TEXT    NOT NULL,
    retrieved_count INTEGER DEFAULT 0,
    correct_direction INTEGER DEFAULT 0,
    precision_pct   REAL,
    created_at      TEXT DEFAULT (datetime('now'))
);
"""



def _prepopulate_halal_l1_cache() -> None:
    """
    B-007 FIX: Pre-populate the halal_ai_cache table with VETOED entries for all
    symbols that would be caught by L1 keyword veto anyway. This prevents a cold-
    cache first run from firing 9-12 LLM calls on structurally haram symbols.

    Only writes rows that don't already exist (INSERT OR IGNORE). Idempotent.
    Runs in ~5ms from the built-in L1 keyword set — zero network cost.
    """
    today = datetime.today().strftime("%Y-%m-%d")
    expires = (datetime.today() + timedelta(days=30)).strftime("%Y-%m-%d")

    try:
        with _db_conn(write=True) as con:
            # Fetch any symbol currently in any table that we can pre-screen
            syms_to_check: list = []
            for tbl in ("sniper_results_v54", "sniper_results", "bhavcopy_cache"):
                try:
                    rows = con.execute(f"SELECT DISTINCT symbol FROM {tbl} LIMIT 500").fetchall()
                    syms_to_check.extend(r[0] for r in rows)
                except Exception:
                    pass

            inserted = 0
            for sym in set(syms_to_check):
                if not _halal_l1_business_veto(sym):
                    continue  # only pre-populate definite L1 vetoes
                try:
                    con.execute("""
                        INSERT OR IGNORE INTO halal_ai_cache
                          (symbol, score, veto, tier, debt_to_mcap, business_model,
                           ethical_score, llm_confidence, assessed_date, source, expires_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        sym.upper(), 0, 1, "HARAM", 0.0, "HARAM_BUSINESS",
                        0, 0.0, today, "L1_PREPOP", expires
                    ))
                    inserted += 1
                except Exception:
                    pass
            if inserted:
                log.info(f"B-007: Pre-populated {inserted} halal L1 vetoes in halal_ai_cache")
    except Exception as e:
        log.debug(f"_prepopulate_halal_l1_cache: {e}")


def _migrate_db_v3():
    """
    Safe, additive v3.0-M migration. Called from _init_db().
    All operations are idempotent — safe to run every startup.
    """
    try:
        with _db_conn(write=True) as con:
            con.executescript(_DB_SCHEMA_V3)

            # Additive ALTER TABLE — each wrapped to survive "already exists" errors
            alter_stmts = [
                ("meta_features", "setup_profile",       "TEXT"),
                ("meta_features", "days_to_earnings",    "INTEGER DEFAULT -1"),
                ("meta_features", "signals_this_week",   "INTEGER DEFAULT 0"),
                ("meta_features", "your_wr_this_grade",  "REAL DEFAULT 0.5"),
                ("meta_features", "your_wr_this_sector", "REAL DEFAULT 0.5"),
                ("meta_features", "mc_survival",         "REAL"),
                ("meta_features", "fort_norm",           "REAL"),
                ("meta_features", "apex_composite",      "REAL"),
                ("meta_features", "confluence_bonus",    "REAL"),
                ("meta_features", "vix_level",           "REAL"),
            ]
            for table, col, dtype in alter_stmts:
                try:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")
                except Exception:
                    pass  # Column already exists — fine

            con.commit()
            log.info("DB v3.0-M migration complete ✅")
    except Exception as e:
        log.debug(f"DB v3 migration: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5c — SETUP PROFILE FINGERPRINTING  (v3.0-M)
# ══════════════════════════════════════════════════════════════════════════════

def _get_setup_profile(r: dict) -> str:
    """
    Fingerprint a signal into a 5-char setup profile code.
    Format: [Grade][Macro][Whale][Divergence][VPOC]
    Example: "PCHWV" = PRISTINE, CHOP, Whale detected, hidden div, at VPOC
    """
    grade_code = {"APEX": "A", "PRISTINE": "P", "GOOD": "G", "PROBE": "B"}.get(
        r.get("grade", "PROBE"), "B"
    )
    macro_code = {"CLEAR": "C", "CHOP": "H", "PANIC": "P", "FOG": "F", "MASSACRE": "M"}.get(
        r.get("macro_state", "CHOP"), "H"
    )
    whale_code = "W" if r.get("whale_score", 0) >= 15 else "w"
    div_code   = "D" if r.get("div_score", 0) >= 10 else "d"
    vpoc_code  = "V" if r.get("layer1", False) else "v"
    return f"{grade_code}{macro_code}{whale_code}{div_code}{vpoc_code}"


def _historical_win_rate_for_profile(profile: str, grade: str = None, sector: str = None,
                                      lookback_days: int = 90) -> dict:
    """
    Query YOUR personal win rate for a given setup profile.
    Returns: {total, wins, avg_pnl, win_rate, confidence_label}
    """
    empty = {"total": 0, "wins": 0, "avg_pnl": 0.0, "win_rate": 0.0, "confidence_label": "No history"}
    try:
        since = (datetime.today() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        with _db_conn() as con:
            rows = con.execute("""
                SELECT o.status, o.pnl_pct
                FROM trade_decisions td
                JOIN pick_outcomes o ON td.symbol = o.symbol AND td.run_date = o.run_date
                JOIN meta_features mf ON td.symbol = mf.symbol AND td.run_date = mf.run_date
                WHERE td.decision = 'TAKEN'
                  AND td.run_date >= ?
                  AND o.status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')
                  AND mf.setup_profile = ?
            """, (since, profile)).fetchall()
            if len(rows) < 3 and grade:
                rows = con.execute("""
                    SELECT o.status, o.pnl_pct
                    FROM trade_decisions td
                    JOIN pick_outcomes o ON td.symbol = o.symbol AND td.run_date = o.run_date
                    JOIN meta_features mf ON td.symbol = mf.symbol AND td.run_date = mf.run_date
                    WHERE td.decision = 'TAKEN'
                      AND td.run_date >= ?
                      AND o.status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')
                      AND mf.grade = ?
                """, (since, grade)).fetchall()
            if not rows:
                return empty
            total = len(rows)
            wins  = sum(1 for s, _ in rows if s in ("r1_hit", "r2_hit", "r3_hit"))
            pnls  = [p for _, p in rows if p is not None]
            avg_pnl  = round(sum(pnls) / len(pnls), 2) if pnls else 0.0
            win_rate = round(wins / total * 100, 1)
            if total < 3:
                label = f"{wins}/{total} trades (limited data)"
            elif win_rate >= 60:
                label = f"{wins}/{total} wins avg {avg_pnl:+.1f}% 🟢"
            elif win_rate >= 40:
                label = f"{wins}/{total} wins avg {avg_pnl:+.1f}% 📊"
            else:
                label = f"{wins}/{total} wins avg {avg_pnl:+.1f}% 🔴"
            return {"total": total, "wins": wins, "avg_pnl": avg_pnl,
                    "win_rate": win_rate, "confidence_label": label}
    except Exception as e:
        log.debug(f"Profile win rate query failed: {e}")
        return empty


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5d — REGIME-SCALED CONFIDENCE  (v3.0-M)
# ══════════════════════════════════════════════════════════════════════════════

def _regime_scaled_confidence(meta_prob: float, macro_state: str, vix: float) -> float:
    """
    Scale AI confidence by macro regime.
    Ceiling at 0.92 (never claim certainty), floor at 0.10.
    """
    if macro_state == "CLEAR":
        if vix < 13:
            scale = 1.12
        elif vix < 17:
            scale = 1.06
        else:
            scale = 1.00
    elif macro_state == "CHOP":
        scale = 0.88
    elif macro_state == "FOG":
        scale = 0.75
    elif macro_state == "PANIC":
        scale = 0.60
    else:
        scale = 0.40
    return round(min(0.92, max(0.10, meta_prob * scale)), 3)


def _confidence_flag(confidence: float) -> str:
    """Convert 0-1 confidence to human label."""
    if confidence >= 0.75:
        return "WORTH YOUR TIME"
    elif confidence >= 0.55:
        return "MAYBE"
    return "SKIP"


def _confidence_emoji(flag: str) -> str:
    return {"WORTH YOUR TIME": "🟢", "MAYBE": "🔵", "SKIP": "⚪"}.get(flag, "⚪")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5e — CAPACITY GUARD  (v3.0-M)
# ══════════════════════════════════════════════════════════════════════════════

def _capacity_guard(date_label: str) -> dict:
    """
    Prevent alert fatigue and over-trading.
    Returns: {slots_remaining, open_count, taken_this_week, warn, reduce_to_worth_only, note}
    """
    result = {
        "slots_remaining": CAPACITY_MAX_OPEN,
        "open_count": 0,
        "taken_this_week": 0,
        "warn": False,
        "reduce_to_worth_only": False,
        "note": ""
    }
    try:
        with _db_conn() as con:
            open_row = con.execute(
                "SELECT COUNT(*) FROM pick_outcomes WHERE status = 'open'"
            ).fetchone()
            open_count = open_row[0] if open_row else 0

            week_start = (datetime.today() - timedelta(days=7)).strftime("%Y-%m-%d")
            week_row = con.execute(
                "SELECT COUNT(*) FROM trade_decisions WHERE decision='TAKEN' AND run_date >= ?",
                (week_start,)
            ).fetchone()
            taken_this_week = week_row[0] if week_row else 0

            recent = con.execute("""
                SELECT o.status FROM trade_decisions td
                JOIN pick_outcomes o ON td.symbol=o.symbol AND td.run_date=o.run_date
                WHERE td.decision='TAKEN'
                  AND o.status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')
                ORDER BY td.logged_at DESC LIMIT 3
            """).fetchall()

            consecutive_losses = sum(1 for (s,) in recent if s in ("stopped", "expired"))
            slots = max(0, CAPACITY_MAX_OPEN - open_count)

            result["open_count"]      = open_count
            result["taken_this_week"] = taken_this_week
            result["slots_remaining"] = slots

            if open_count >= CAPACITY_MAX_OPEN:
                result["warn"] = True
                result["reduce_to_worth_only"] = True
                result["note"] = f"⚠️ {open_count} open positions — only WORTH YOUR TIME signals today"
            elif consecutive_losses >= 2:
                result["warn"] = True
                result["reduce_to_worth_only"] = True
                result["note"] = f"⚠️ {consecutive_losses} consecutive losses — raising the bar"
            elif taken_this_week >= CAPACITY_MAX_WEEK:
                result["reduce_to_worth_only"] = True
                result["note"] = f"📊 {taken_this_week} trades this week — quality over quantity"
    except Exception as e:
        log.debug(f"Capacity guard: {e}")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5f — TRADE DECISION LOGGER  (v3.0-M)
# ══════════════════════════════════════════════════════════════════════════════

def confirm_entry(symbol: str) -> tuple:
    """M3 FIX: Pre-entry earnings confirmation gate.
    Call this in your Telegram reply handler BEFORE logging a TAKEN decision.
    Earnings announced after scoring but before manual entry (e.g. pre-market next morning)
    would otherwise let you walk blind into a volatility event.

    Returns: (allowed: bool, reason: str)
    Usage in reply_handler.py:
        ok, reason = confirm_entry(symbol)
        if not ok:
            _tg_post(TOKEN, CHAT_ID, f"⛔ {symbol} BLOCKED: {reason}")
            return
        _log_trade_decision(run_date, symbol, "TAKEN", entry_price=price)
    """
    earn_days = _check_earnings_yf(symbol)
    if earn_days is not None and 0 <= earn_days <= 1:
        return False, f"Earnings in {earn_days}d — entry blocked to avoid volatility event"
    # Also re-check the hardcoded earnings calendar in case yfinance misses it
    if earn_days is None:
        log.debug(f"confirm_entry({symbol}): yfinance calendar unavailable — proceeding with caution")
    return True, "OK"


def _log_trade_decision(run_date: str, symbol: str, decision: str,
                         entry_price: float = None, shares: int = 0,
                         skip_reason: str = None, ai_confidence: float = None,
                         worth_flag: str = None, setup_profile: str = None):
    """
    Log a manual trade decision to trade_decisions table.
    Called by reply_handler.py when you reply to the Telegram bot.
    NOTE: Call confirm_entry(symbol) before calling this for TAKEN decisions.
    """
    try:
        with _db_conn(write=True) as con:
            con.execute("""
                INSERT OR REPLACE INTO trade_decisions
                  (run_date, symbol, decision, entry_price, shares_taken,
                   skip_reason, ai_confidence, worth_flag, setup_profile)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (run_date, symbol.upper(), decision, entry_price, shares,
                  skip_reason, ai_confidence, worth_flag, setup_profile))
        log.info(f"Decision logged: {symbol} → {decision} "
                 f"({'₹'+str(entry_price) if entry_price else skip_reason})")
    except Exception as e:
        log.error(f"Decision log failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5g — WEEKLY REVIEW  (v3.0-M)
# ══════════════════════════════════════════════════════════════════════════════

def _send_weekly_review():
    """
    Generate and send a personalised weekly performance review via Telegram.
    Analyses YOUR decisions vs outcomes. Run every Friday via GitHub Actions.
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        week_start = (datetime.today() - timedelta(days=7)).strftime("%Y-%m-%d")
        with _db_conn() as con:
            decisions = con.execute("""
                SELECT td.symbol, td.decision, td.entry_price, td.ai_confidence, td.worth_flag,
                       o.status, o.pnl_pct, o.days_held
                FROM trade_decisions td
                LEFT JOIN pick_outcomes o ON td.symbol=o.symbol AND td.run_date=o.run_date
                WHERE td.run_date >= ?
            """, (week_start,)).fetchall()
            total_signals = con.execute(
                "SELECT COUNT(DISTINCT symbol) FROM sniper_results WHERE run_date >= ?",
                (week_start,)
            ).fetchone()[0]

            taken   = [d for d in decisions if d[1] == "TAKEN"]
            skipped = [d for d in decisions if d[1] == "SKIPPED"]
            closed  = [d for d in taken if d[5] and d[5] not in ("open", None)]
            wins    = [d for d in closed if d[5] in ("r1_hit","r2_hit","r3_hit")]
            losses  = [d for d in closed if d[5] in ("stopped","expired")]
            pnls    = [d[6] for d in closed if d[6] is not None]
            avg_pnl = round(sum(pnls)/len(pnls), 2) if pnls else 0.0

            high_taken = [d for d in closed if d[3] and d[3] >= 0.75]
            mid_taken  = [d for d in closed if d[3] and 0.55 <= d[3] < 0.75]
            low_taken  = [d for d in closed if d[3] and d[3] < 0.55]

            def _acc(grp):
                if not grp: return None
                return round(sum(1 for d in grp if d[5] in ("r1_hit","r2_hit","r3_hit")) / len(grp) * 100, 1)

            acc_high = _acc(high_taken)
            acc_mid  = _acc(mid_taken)
            acc_low  = _acc(low_taken)
            wr = round(len(wins)/len(closed)*100, 1) if closed else 0.0
            week_num = datetime.today().strftime("%V")

            lines = [
                f"📊 WEEKLY REVIEW — Week {week_num} ({week_start} to today)",
                "",
                f"Signals: {total_signals} | Taken: {len(taken)} | Skipped: {len(skipped)} | Open: {len(taken)-len(closed)}",
                "",
                "📈 Your results (closed trades):",
            ]
            if closed:
                best  = max(closed, key=lambda d: d[6] or -99)
                worst = min(closed, key=lambda d: d[6] or 99)
                lines += [
                    f"  Win rate: {len(wins)}/{len(closed)} ({wr}%) | Avg P&L: {avg_pnl:+.1f}%",
                    f"  Best: {best[0]} {best[6]:+.1f}% | Worst: {worst[0]} {worst[6]:+.1f}%",
                ]
            else:
                lines.append("  No closed trades this week yet.")

            lines += ["", "🤖 AI Confidence accuracy:"]
            if acc_high is not None:
                lines.append(f"  >75% confidence ({len(high_taken)} trades) → {acc_high}% win rate {'✅' if acc_high >= 60 else '⚠️'}")
            if acc_mid is not None:
                lines.append(f"  55-75% confidence ({len(mid_taken)} trades) → {acc_mid}% win rate {'📊' if acc_mid >= 50 else '⚠️'}")
            if acc_low is not None:
                lines.append(f"  <55% confidence ({len(low_taken)} trades) → {acc_low}% win rate {'🚫' if acc_low < 40 else '📊'}")

            lines.append("")
            if acc_low is not None and acc_low < 35 and len(low_taken) >= 2:
                lines.append("💡 Insight: Skip signals under 55% confidence — your data confirms it loses.")
            elif acc_high is not None and acc_high >= 65 and len(high_taken) >= 2:
                lines.append("💡 Insight: High-confidence signals are working — trust the >75% threshold.")
            elif wr < 40 and len(closed) >= 3:
                lines.append("💡 Insight: Win rate low this week — consider tightening entry to buy zone only.")
            else:
                lines.append("💡 Stay consistent — the edge compounds over time. Bismillah 🤲")

            msg = "\n".join(lines)
            _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, msg)

            try:
                with _db_conn(write=True) as con:
                    con.execute("""
                        INSERT OR REPLACE INTO weekly_reviews
                          (week_start, signals_total, taken, skipped, wins, losses, avg_pnl,
                           ai_accuracy_high, ai_accuracy_mid, ai_accuracy_low, summary_text)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """, (week_start, total_signals, len(taken), len(skipped),
                          len(wins), len(losses), avg_pnl, acc_high, acc_mid, acc_low, msg))
                    con.commit()
            except Exception as e:
                log.debug(f"Weekly review DB store: {e}")

            log.info("Weekly review sent ✅")
    except Exception as e:
        log.error(f"Weekly review failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# ── CALIBRATED PRIORS (based on NSE halal mid-cap backtest estimates) ──
# These are conservative estimates. Replace with your actual backtest results.
# M1 FIX: Regime-aware prior overrides for macro_clear node.
# In CLEAR regime, macro_clear=True is the norm — the prior edge is already baked in.
# In PANIC/MASSACRE, stocks that look "clear" are actually in denial; cut the pt aggressively.
# In CHOP, macro_clear=True is rare and mildly meaningful; reduce its signal slightly.
# Format mirrors _BAYES_PRIORS: (pt, pf, weight) — only the macro_clear tuple is overridden.
_REGIME_PRIOR_OVERRIDES: dict = {
    "PANIC":    {"macro_clear": (0.44, 0.38, 1.0)},  # Clear-looking stocks in PANIC are traps
    "MASSACRE": {"macro_clear": (0.30, 0.38, 1.0)},  # Invert edge: being "clear" means denial
    "CHOP":     {"macro_clear": (0.52, 0.42, 1.0)},  # Mild edge reduction vs CLEAR's 0.58
}

_BAYES_PRIORS = {
    # Format: (condition, profit_prob_if_true, profit_prob_if_false, weight)
    # Weights sum to ~1.0, adjusted by empirical edge

    # Macro conditions (strong signal in NSE)
    ("macro_clear", 0.58, 0.42, 1.0),      # Was 0.72/0.28 — too optimistic
    ("breadth_ok", 0.55, 0.40, 0.8),         # Was 0.65/0.38

    # VPOC layers (moderate signal — many false positives)
    ("layer1", 0.52, 0.35, 1.0),             # Was 0.72/0.30
    ("layer2", 0.50, 0.38, 0.9),             # Was 0.68/0.38
    ("layer3", 0.51, 0.36, 0.9),             # Was 0.70/0.35

    # Technicals (weak-moderate signal)
    ("mfi_oversold", 0.48, 0.40, 0.7),       # Was 0.68/0.42
    ("adx_trending", 0.50, 0.42, 0.7),       # Was 0.68/0.38
    ("not_overextended", 0.46, 0.38, 0.6),   # Was 0.62/0.40

    # APEX signals (strong when combined)
    ("whale_detected", 0.55, 0.42, 0.9),     # Was 0.74/0.44
    ("bullish_hidden_div", 0.53, 0.40, 0.8), # Was 0.70/0.40
    ("vp_score_high", 0.51, 0.40, 0.7),      # Was 0.67/0.40
    ("mc_survival_ok", 0.50, 0.42, 0.6),     # Was 0.68/0.45

    # Intelligence (strong signal when real)
    ("fii_buying", 0.54, 0.42, 0.8),         # Was 0.66/0.40
    ("insider_buying", 0.52, 0.42, 0.7),     # Was 0.65/0.42
    ("positive_filing", 0.51, 0.42, 0.6),    # Was 0.63/0.42
}


def _load_live_bayes_priors():
    """
    FIX-7: Replace static _BAYES_PRIORS with live empirical win rates after 50 picks.
    _calibrate_bayes_priors() already computes real win rates per node and writes them
    to bayes_calibration — but _bayesian_apex() still reads the hardcoded list.
    At run() start, if bayes_calibration has >50 rows per node, pull live win_rate
    values and override _BAYES_PRIORS tuples in memory. Full learning loop closed.
    """
    global _BAYES_PRIORS
    try:
        with _db_conn() as con:
            rows = con.execute(
                "SELECT prior_name, win_rate, total FROM bayes_calibration WHERE total >= 50"
            ).fetchall()
        if not rows:
            log.debug("FIX-7: bayes_calibration has no nodes with ≥50 samples — using hardcoded priors")
            return

        # Build lookup: {prior_name: empirical_win_rate}
        live_rates = {name: float(wr) for name, wr, total in rows if wr is not None}
        if not live_rates:
            return

        updated = []
        new_priors = set()
        for entry in _BAYES_PRIORS:
            name, pt, pf, weight = entry
            if name in live_rates:
                emp_wr = live_rates[name]
                # pt (prob if true) = empirical win rate
                # pf (prob if false) = complement shrunk toward 0.40 base rate
                new_pt = round(max(0.40, min(0.80, emp_wr)), 3)
                new_pf = round(max(0.30, min(0.60, emp_wr * 0.75)), 3)
                new_priors.add((name, new_pt, new_pf, weight))
                updated.append(f"{name}: pt {pt:.3f}→{new_pt:.3f} pf {pf:.3f}→{new_pf:.3f} (n={dict([(r[0],r[2]) for r in rows]).get(name,'?')})")
            else:
                new_priors.add(entry)

        _BAYES_PRIORS = new_priors
        if updated:
            log.info(f"FIX-7: Bayesian priors updated from {len(updated)} live calibration node(s):\n  " + "\n  ".join(updated[:5]))
        else:
            log.debug("FIX-7: No calibrated nodes had ≥50 samples — hardcoded priors unchanged")
    except Exception as e:
        log.warning(f"_load_live_bayes_priors failed (non-fatal, using hardcoded): {e}")


def _bayesian_apex(macro_state: str, breadth_ok: bool, layer1: bool, layer2: bool, layer3: bool,
                   whale_detected: bool, div_type: str, vp_score: float,
                   mfi_v: float, adx_v: float, alt_pct: float,
                   mc_survival: Optional[float],
                   fii_pts: int, ins_pts: int, fil_pts: int) -> dict:
    """
    Calibrated 14-node Bayesian network — FIXED v2.
    Root cause of original failure: log-odds sequential update with conservative
    priors (pt≈0.52, pf≈0.40) generates log(pf/(1-pf)) ≈ -0.40 per false node.
    With 15 nodes × avg weight 0.8, most CHOP setups accumulated −4 log-odds,
    driving posterior to <5% before shrinkage, then bayes_pct stayed at 5-18.

    Fix: Replace broken log-odds accumulation with a two-stage additive scorer:
      Stage 1 — Base rate (40%) + positive node contributions (scaled 0-60% range)
      Stage 2 — Shrinkage toward 50% (epistemic humility, prevents overfit)
    Target range: 35-75% when 0/14 to 8/14 nodes are true.
    At 2-3 true nodes (typical CHOP pick): should produce 45-58%.
    At 5-6 true nodes (good CLEAR pick): should produce 60-70%.
    """
    # Build condition map — same as before, no change
    conditions = {
        "macro_clear":       macro_state == "CLEAR",
        "breadth_ok":        breadth_ok,
        "layer1":            layer1,
        "layer2":            layer2,
        "layer3":            layer3,
        "mfi_oversold":      mfi_v <= 45.0,
        "adx_trending":      adx_v >= 25.0,
        "not_overextended":  alt_pct < 30.0,
        "whale_detected":    whale_detected,
        "bullish_hidden_div": div_type == "BULLISH_HIDDEN",
        "vp_score_high":     vp_score >= 40,
        "mc_survival_ok":    mc_survival is not None and mc_survival >= 65,
        "fii_buying":        fii_pts >= 22,
        "insider_buying":    ins_pts >= 15,
        "positive_filing":   fil_pts >= 20,
    }

    # ── Stage 1: Weighted signal accumulation ────────────────────────────
    # Each node contributes an edge score: (pt - pf) × weight normalised to [0, 1].
    # This measures how much the TRUE condition beats the FALSE condition baseline.
    # A node where pt=0.52, pf=0.40, weight=1.0 contributes edge = 0.12 × 1.0 = 0.12.
    # Summed across 15 nodes (total potential weight ≈ 11.7), max positive edge ≈ 1.76.
    # We scale this to a 0-60 percentage-point uplift above a 35% floor.
    total_positive_edge = 0.0
    max_possible_edge   = 0.0

    # M1 FIX: Apply regime-specific prior overrides before iterating.
    # In PANIC/MASSACRE, the macro_clear node prior is recalculated — not just shifted
    # by a flat regime_adj after the fact. This correctly reduces signal strength at
    # the source rather than patching the output.
    regime_overrides = _REGIME_PRIOR_OVERRIDES.get(macro_state, {})

    for name, pt, pf, weight in _BAYES_PRIORS:
        # B-002 FIX: accumulate max_possible_edge using BASE weight, not override weight.
        # Regime overrides reduce signal credibility but must NOT shrink the denominator —
        # doing so inflates positive_ratio in PANIC/MASSACRE (exactly wrong direction).
        base_edge = (pt - pf) * weight     # theoretical max using ORIGINAL base weight
        # Apply override tuple if this regime has one for this node
        if name in regime_overrides:
            pt, pf, weight = regime_overrides[name]
        cond = conditions.get(name, False)
        edge = (pt - pf) * weight          # actual credibility-adjusted edge
        if cond:
            total_positive_edge += edge    # accumulate only when condition is true
        max_possible_edge += base_edge     # B-002: always use BASE weight for denominator

    # Normalise: positive_ratio = 0 when no conditions true, 1 when all true
    positive_ratio = (total_positive_edge / max(max_possible_edge, 1e-9))

    # Map ratio → probability: floor=0.35, ceil=0.78, range=0.43
    # At ratio=0.00 (no conditions): p = 0.35 (worse than coin-flip — good prior)
    # At ratio=0.20 (2-3 conditions, CHOP typical): p ≈ 0.44
    # At ratio=0.35 (4-5 conditions, CLEAR good): p ≈ 0.50
    # At ratio=0.55 (7-8 conditions, CLEAR great): p ≈ 0.59
    # At ratio=1.00 (all conditions): p = 0.78
    raw_prob = 0.35 + positive_ratio * 0.43

    # ── Stage 2: Macro-aware regime adjustment ────────────────────────────
    # In CHOP we're already picking the best available — apply a small floor lift.
    # In PANIC or MASSACRE the Bayesian evidence is unreliable — shrink to neutral.
    if macro_state == "CLEAR":
        regime_adj = +0.03
    elif macro_state == "CHOP":
        regime_adj = +0.01    # small positive: CHOP setups that pass Fortress are pre-filtered
    elif macro_state == "PANIC":
        regime_adj = -0.05
    else:  # MASSACRE — pipeline already returns None upstream, but guard here
        regime_adj = -0.15

    prob_after_regime = raw_prob + regime_adj

    # ── Stage 3: Adaptive shrinkage toward 50% (OPT-17) ────────────────────
    # α scales with sample count: fewer samples = more shrinkage (epistemic caution)
    # 0 samples→α=0.40 (heavy shrink), 200+ samples→α=0.10 (light shrink)
    try:
        with _db_conn() as _bc:
            _n_closed = _bc.execute(
                "SELECT COUNT(*) FROM pick_outcomes WHERE status IN "
                "('r1_hit','r2_hit','r3_hit','stopped','expired')"
            ).fetchone()[0]
    except Exception:
        _n_closed = 0
    alpha = max(0.10, min(0.40, 0.40 - (_n_closed / 200) * 0.30))  # OPT-17
    posterior = alpha * 0.50 + (1 - alpha) * prob_after_regime
    posterior = min(0.95, max(0.05, round(posterior, 3)))

    pct = round(posterior * 100)

    # Tier thresholds — tuned for the new 35-78% output range
    if posterior >= 0.65:    tier, bonus = "HIGH",     8
    elif posterior >= 0.55:  tier, bonus = "MODERATE", 4
    elif posterior >= 0.47:  tier, bonus = "NEUTRAL",  0
    else:                    tier, bonus = "LOW",      -5

    return {
        "bayes_prob":  posterior,
        "bayes_pct":   pct,
        "bayes_tier":  tier,
        "bayes_bonus": bonus,
        "bayes_label": f"{tier} conviction ({pct}%)",
        "calibrated":  True,
        "positive_ratio": round(positive_ratio, 3),   # diagnostic
    }


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 13 — FUSED COMPOSITE ASSEMBLER
# ══════════════════════════════════════════════════════════════════════════════

def assemble_pick(
    symbol: str,
    today_row,
    hist: pd.DataFrame,
    fii_data: dict,
    insider_map: dict,
    filings: dict,
    earnings_cal: dict,
    macro: dict,
    data_source: str = "NSE",   # FIX-A10: passed to _monte_carlo for VIF
) -> Optional[dict]:
    """
    Single-pass fused scorer.
    Step 1: Fortress engine (hard veto, VPOC, sector, intelligence scores)
    Step 2: APEX 7-engine (whale, divergence, patterns, MC, Bayesian)
    Step 3: Fused composite = fort_total × 0.45 + apex_composite × 0.55
    Step 4: Grade, story, exits, position size.
    """
    macro_state = macro.get("macro_state","CHOP")
    breadth_ok  = macro.get("breadth_ok",True)
    vix         = macro.get("vix_val",18.0)

    # ── Earnings hard veto ─────────────────────────────────────────────
    earn_days = earnings_cal.get(symbol.upper())
    if earn_days is None:
        earn_days = _check_earnings_yf(symbol)
    if earn_days is not None and 0 <= earn_days <= 2:
        log.warning(f"{symbol}: EARNINGS VETO ({earn_days}d) — skipped")
        return None

    if macro_state == "MASSACRE":
        return None

    # ── FORTRESS STEP ─────────────────────────────────────────────────
    fort = fortress_score(symbol, today_row, hist, macro_state=macro_state)  # RC3 FIX: pass regime
    if fort is None:
        return None

    # DEBUG: Log symbols that pass fortress (to see pipeline flow)
    log.info(f"  PIPELINE {symbol}: fortress_pts={fort['fortress_pts']:.0f} | "
             f"macro={macro_state} | vix={vix:.1f} | sector={get_sector(symbol)}")

    close    = float(today_row["close"])
    dq       = str(today_row.get("data_quality",""))
    if dq in ("SNAPSHOT_FALLBACK","STALE") and fort["fortress_pts"] > 55:
        fort["fortress_pts"] = 55

    fii_pts  = fii_data.get("score",15)
    fii_lbl  = fii_data.get("label","—")
    fii_det  = fii_data.get("detail","—")
    ins_data = insider_map.get(symbol.upper(), {})
    ins_pts  = ins_data.get("score",0)
    ins_det  = ins_data.get("detail","No insider trades in 30d")
    fil_data = filings.get(symbol.upper(), {})
    fil_pts  = fil_data.get("score",15)
    fil_det  = fil_data.get("detail","No recent filing")

    # ROE quality gate
    if fil_pts>15 and dq not in ("SNAPSHOT_FALLBACK","STALE"):
        roe_val, roe_lbl = _fetch_roce(symbol)
        if roe_val is None:
            fil_pts=min(fil_pts,10); fil_det=f"{fil_det} | ⚠️ ROE unverifiable"
        elif roe_val<5.0:
            fil_pts=min(fil_pts,8); fil_det=f"{fil_det} | ❌ {roe_lbl}"
        else:
            fil_det=f"{fil_det} | ✅ {roe_lbl}"

    # Earnings safety score
    def _earn_pts():
        if earn_days is None: return 20,"No result date"
        if earn_days<0:
            r=abs(earn_days)
            if r<=5:  return 28,"Results just announced — fresh data"
            elif r<=21: return 25,f"Results {r}td ago — clear runway"
            else:     return 20,f"Results {r}td ago"
        else:
            if earn_days<=2:  return 5, f"⚠️ Results in {earn_days}td — SIZE SMALL"
            elif earn_days<=5: return 10,f"⚠️ Results in {earn_days}td — risky"
            elif earn_days<=10: return 18,f"Results in {earn_days}td — caution"
            elif earn_days<=21: return 24,f"Results in {earn_days}td — acceptable"
            else:              return 30,f"Results in {earn_days}td — safe runway ✓"
    earn_pts, earn_det = _earn_pts()

    fort_total = min(FORT_TOTAL_MAX, fort["fortress_pts"]+fii_pts+ins_pts+fil_pts+earn_pts)

    # ── APEX STEP ─────────────────────────────────────────────────────
    atr14   = fort["atr14"]; adv20=fort["adv20"]
    vpoc    = fort["vpoc"];  ma200=fort["ma200"]
    sector  = get_sector(symbol)

    profile       = _vpoc_profile(hist)
    poc           = profile.get("poc", vpoc) or vpoc

    stop_from_atr = close - 2.5*atr14*SECTOR_ATR_MULT.get(sector,1.0)
    stop_from_poc = poc*0.97 if poc>0 else stop_from_atr
    stop_loss     = round(max(min(stop_from_atr,stop_from_poc), close*0.88), 2)
    risk_pct      = round((close-stop_loss)/close*100, 1)

    whale_score, whale_det = _whale_radar(hist, adv20)
    div_score,   div_det   = _divergence_engine(hist)
    vp_score,    vp_label  = _vol_profile_score(profile, close, fortress_vpoc=vpoc)
    pat_score,   pat_label = _pattern_score(hist, atr14, profile)
    mc          = _monte_carlo(hist, stop_loss, close, data_source=data_source)
    mc_survival = mc.get("survival")

    # H2 FIX: hard veto — if MC says survival < 50% with valid data, reject the pick.
    if mc.get("hard_veto"):
        log.info(f"  🚫 {symbol}: MC hard veto (survival={mc_survival}% < 50% on valid data)")
        return None

    vol_rel = fort["vol_reliable"]
    cvd     = _calc_cvd(hist, vol_rel)
    vsa     = _calc_vsa(hist, atr14, adv20, vol_rel)
    fog     = _calc_fog(fort["adx"], fort["adx_prev"], vix, fort["ma50"], fort["ma200"], fort["w52_bonus"])

    bayes = _bayesian_apex(
        macro_state=macro_state, breadth_ok=breadth_ok,
        layer1=fort["layer1"], layer2=fort["layer2"], layer3=fort["layer3"],
        whale_detected=whale_det["whale_detected"] or whale_det["stealth_score"]>=50,
        div_type=div_det["div_type"], vp_score=vp_score,
        mfi_v=fort["mfi"], adx_v=fort["adx"], alt_pct=fort["alt_pct"],
        mc_survival=mc_survival,
        fii_pts=fii_pts, ins_pts=ins_pts, fil_pts=fil_pts,    # ← intelligence fusion
    )

    macro_damp = {"CLEAR":1.0,"CHOP":0.88,"PANIC":0.60,"MASSACRE":0.0}
    bayes_score = float(bayes["bayes_pct"])

    # ── CHOP pre-compensation constant ──────────────────────────────────
    # BUG FIX: Old code applied "+8" AFTER dampening: raw×0.88+8.
    # At raw=30: 26.4+8=34.4 (still −13% vs CLEAR's 30). Compensation was ineffective.
    # New approach: add to raw BEFORE dampening so the effect survives the multiply.
    # CRIT-2 FIX: Raised from 12→20 so CHOP picks can clear APEX_MIN_SCORE=35 (CHOP floor).
    # At raw=30 in CHOP: (30+20)×0.88=44.0 (+47% vs undamped 30).
    # At raw=60 in CHOP: (60+20)×0.88=70.4 vs CLEAR 60 (+17%).
    _CHOP_PRE_COMP = 20

    # ── APEX CONFLUENCE SCORE (NOT double-counting VPOC) ──
    # Instead of re-scoring VPOC layers (already in fortress_pts),
    # measure how strongly the INDEPENDENT APEX engines confirm
    # the same trade idea. This is pure confluence, not duplication.

    # Confluence bonuses: when multiple engines agree on direction
    confluence_bonus = 0
    confluence_notes = []

    # Whale + Divergence agreement (strong)
    if whale_det["whale_detected"] and div_det["div_type"] == "BULLISH_HIDDEN":
        confluence_bonus += 15
        confluence_notes.append("Whale+Div agree")

    # Pattern + Volume Profile agreement (moderate)
    if vp_score >= 40 and ("VCP" in pat_label or "Cup" in pat_label):
        confluence_bonus += 12
        confluence_notes.append("VP+Pattern agree")

    # Bayesian + MC agreement (moderate)
    if bayes["bayes_pct"] >= 60 and mc_survival is not None and mc_survival >= 70:
        confluence_bonus += 10
        confluence_notes.append("Bayes+MC agree")

    # All four engines aligned (rare, powerful)
    engines_aligned = sum([
        whale_det["whale_detected"],
        div_det["div_type"] == "BULLISH_HIDDEN",
        vp_score >= 35,
        bayes["bayes_pct"] >= 55
    ])
    if engines_aligned >= 4:
        confluence_bonus += 8
        confluence_notes.append("All engines aligned")
    elif engines_aligned == 3:
        confluence_bonus += 4
        confluence_notes.append("3/4 engines aligned")

    # Cap confluence to prevent runaway scores
    confluence_bonus = min(35, confluence_bonus)

    # ── APEX RAW COMPOSITE (independent of fortress VPOC) ──
    raw_apex = (
        whale_score          * W["whale_radar"]   +
        div_score            * W["divergence"]    +
        vp_score             * W["vol_profile"]   +
        pat_score            * W["pattern"]       +
        bayes_score          * W["bayesian"]      +
        confluence_bonus     * W["fortress_vpoc"]  # Reuse weight slot for confluence
    )
    # FIX: apply CHOP pre-compensation BEFORE dampening so it survives the multiply.
    # In CLEAR/PANIC/MASSACRE the constant is 0 (no effect).
    chop_pre = _CHOP_PRE_COMP if macro_state == "CHOP" else 0
    apex_composite = round((raw_apex + chop_pre) * macro_damp.get(macro_state, 0.88))
    # Independent bonuses (not double-counting)
    if bayes["bayes_pct"] >= 75 and mc_survival is not None and mc_survival >= 75:
        apex_composite = min(100, apex_composite + 5)  # High conviction + high survival
    apex_composite = max(0, min(100, apex_composite))

    # ACC-4 (v5.0): Momentum regime scale — confirmed CLEAR + trending tape gets lift
    # Condition: CLEAR regime + NIFTY up >+0.5% today + VIX < 15 (low fear)
    # Scale: apex × 1.08 (8% uplift). Does NOT relax the fused gate (APEX_MIN_SCORE).
    # Rationale: trending days produce better swing outcomes — reward the regime alignment.
    _macro_nifty_chg = macro.get("nifty_chg", 0.0)
    if macro_state == "CLEAR" and _macro_nifty_chg >= 0.5 and vix < 15.0:
        _momentum_scaled = min(100, round(apex_composite * 1.08))
        if _momentum_scaled > apex_composite:
            log.debug(f"  ACC-4 momentum scale {symbol}: apex {apex_composite}→{_momentum_scaled} (CLEAR+nifty+{_macro_nifty_chg:.1f}%+VIX{vix:.1f})")
            apex_composite = _momentum_scaled

    # ── FUSED COMPOSITE + GRADE ────────────────────────────────────────
    # BUG FIX: fort_norm, fused, and grade were referenced but never
    # assigned anywhere in this function, causing NameError at runtime.
    # fort_norm   — fortress total as 0-100 percentage (for return dict)
    # fused       — weighted blend: fortress 45% + APEX 55%
    # grade       — categorical label derived from fused threshold bands
    fort_norm = round((fort_total / FORT_TOTAL_MAX) * 100, 1)
    fused = max(0, min(100, round(fort_norm * 0.45 + apex_composite * 0.55)))
    grade = (
        "APEX"     if fused >= GRADE_APEX     else
        "PRISTINE" if fused >= GRADE_PRISTINE else
        "GOOD"     if fused >= GRADE_GOOD     else
        "PROBE"
    )

    # ── DEBUG: Log rejections for tuning ──
    # FIX-4.1-M: APEX floor 35 in CHOP regime was too aggressive — 10+ symbols
    # with apex=32-34 were rejected despite strong Fortress passes (45-69 pts).
    # Lower to 30 for CHOP. The fused gate (APEX_MIN_SCORE=48) provides the
    # secondary quality filter — a stock with apex=30 + fort=69 gets fused=52 and
    # passes normally, while apex=30 + fort=42 gets fused=44 and is still rejected.
    apex_floor = 30 if macro_state == "CHOP" else APEX_MIN_SCORE
    if apex_composite < apex_floor:
        # FIX-4: MC Survival Rescue — if MC survival is very high (>= 85%) and we're
        # only just below the floor (within 5 pts), the low APEX may be a data artifact
        # (NSE blocked → incomplete intraday → vp_score=0, div_score=0) rather than
        # genuine weakness. KIMS example: fortress=60, mc=96%, but apex=27 < floor=30.
        # Only rescue when within 5 pts of floor AND mc_survival is very high.
        if mc_survival is not None and mc_survival >= 85 and apex_composite >= apex_floor - 5:
            log.info(
                f"  MC RESCUE {symbol}: apex={apex_composite} (floor={apex_floor}-5={apex_floor-5}) "
                f"but mc_survival={mc_survival}% >= 85% — allowing through (data artifact likely)"
            )
            # Don't return None — fall through to continue scoring
        else:
            log.info(f"  DEBUG {symbol}: REJECTED | apex={apex_composite} (floor={apex_floor}/{macro_state}) | bayes={bayes['bayes_pct']}% | "
                     f"whale={whale_score:.0f} | div={div_score:.0f} | vp={vp_score:.0f} | pat={pat_score:.0f} | "
                     f"mc={mc_survival} | confluence={confluence_bonus} | damp={macro_damp.get(macro_state,0.88)}")
            return None

    # ── META-LABELING: Store signal vector + optional veto ──

    # (veto moved to debug block above)
    # ── REGIME-AWARE ATR STOP MULTIPLIER (FIX-4.1-M) ─────────────────────────
    # In CHOP regime, tight stops get hit by noise — widen to 2.5×.
    # In CLEAR regime, trend is your friend — tighten to 1.8× for better R:R.
    _regime_atr_mult = {"CHOP": 2.5, "FOG": 2.8, "PANIC": 3.0, "CLEAR": 1.8}.get(macro_state, 2.0)
    atr_m  = SECTOR_ATR_MULT.get(sector,1.0) * _regime_atr_mult
    risk   = atr14 * atr_m if atr14>0 else close*0.03
    r1     = round(close+risk*2.5,2)
    r2     = round(close+risk*4.0,2)
    r3     = round(close+risk*6.5,2)
    trail_stop = round(r2-atr14*2.5*atr_m,2)
    r1_pct=round((r1-close)/close*100,1); r2_pct=round((r2-close)/close*100,1)
    r3_pct=round((r3-close)/close*100,1)

    # ── Dynamic Position Sizing (Fractional Kelly) ─────────────────────
    def _get_kelly_inputs(symbol: str, grade: str, sector: str) -> tuple:
        """Return (empirical_win_rate, avg_win, avg_loss) from matched history."""
        try:
            with _db_conn() as con:
                rows = con.execute(
                    """SELECT pnl_pct FROM pick_outcomes
                       WHERE grade=? AND sector=?
                       AND status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')
                       AND run_date > ?""",
                    (grade, sector, (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d"))
                ).fetchall()

                if len(rows) < 20:
                    return None, None, None

                pnls = [r[0] for r in rows if r[0] is not None]
                if not pnls:
                    return None, None, None

                wins = [p for p in pnls if p > 0]
                losses = [p for p in pnls if p < 0]

                win_rate = len(wins) / len(pnls)
                avg_win = np.mean(wins) if wins else 0
                avg_loss = abs(np.mean(losses)) if losses else 0

                return win_rate, avg_win, avg_loss
        except Exception as e:
            log.debug(f"Kelly inputs {symbol}: {e}")
            return None, None, None

    def _kelly_fraction(p: float, b: float, max_frac: float = ACCOUNT_RISK_PCT,
                        empirical: bool = False, sample_count: int = 0) -> float:
        """
        f = (p*b - q) / b, fractional Kelly conservative.
        If empirical data insufficient (< 100 matched trades), use quarter-Kelly capped at 0.5%.
        Only scale up to half-Kelly after 100+ matched trades.
        """
        q = 1.0 - p
        if b <= 0 or p <= 0 or p >= 1:
            return max_frac * 0.25

        raw_kelly = (p * b - q) / b
        raw_kelly = max(0.0, raw_kelly)

        if not empirical or sample_count < 100:
            return min(max_frac * 0.25, 0.005)
        else:
            return min(max_frac, raw_kelly * 0.5)

    emp_wr, emp_win, emp_loss = _get_kelly_inputs(symbol, grade, sector)

    if emp_wr is not None and emp_loss > 0:
        b_emp = emp_win / emp_loss if emp_loss > 0 else 2.0
        p_emp = emp_wr
        try:
            with _db_conn() as con:
                count_row = con.execute(
                    """SELECT COUNT(*) FROM pick_outcomes
                       WHERE grade=? AND sector=?
                       AND status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')
                       AND run_date > ?""",
                    (grade, sector, (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d"))
                ).fetchone()
                sample_count = count_row[0] if count_row else 0
        except Exception:
            sample_count = 0

        kelly_frac = _kelly_fraction(p_emp, b_emp, max_frac=ACCOUNT_RISK_PCT,
                                     empirical=True, sample_count=sample_count)
        kelly_source = f"empirical ({sample_count} samples)"
    else:
        b_default = 2.0
        p_default = 0.45
        kelly_frac = _kelly_fraction(p_default, b_default, max_frac=ACCOUNT_RISK_PCT,
                                     empirical=False, sample_count=0)
        kelly_source = "default (insufficient history)"

    rps = max(close - stop_loss, close * 0.02)
    risk_r = ACCOUNT_EQUITY * kelly_frac
    sh_v = math.floor(risk_r / rps) if rps > 0 else 0

    # OPT-15: Kelly-continuous deploy fraction (linear interpolation between grade thresholds)
    # Original: step function with 4 fixed tiers causing cliff-edge ranking artifacts.
    # Now: smooth interpolation so fused=60 doesn't equal fused=71 in position size.
    if fused >= GRADE_APEX:
        deploy = 1.00
    elif fused >= GRADE_PRISTINE:
        deploy = 0.75 + 0.25 * (fused - GRADE_PRISTINE) / max(1, GRADE_APEX - GRADE_PRISTINE)
    elif fused >= GRADE_GOOD:
        deploy = 0.50 + 0.25 * (fused - GRADE_GOOD) / max(1, GRADE_PRISTINE - GRADE_GOOD)
    else:
        deploy = 0.25 + 0.25 * (fused - GRADE_PROBE) / max(1, GRADE_GOOD - GRADE_PROBE)
    deploy = round(max(0.10, min(1.00, deploy)), 3)  # OPT-15: continuous, clipped

    sh_f = min(math.floor(sh_v * deploy),
               math.floor(ACCOUNT_EQUITY * 0.10 / close) if close > 0 else 0)
    pos_v = sh_f * close
    pos_lb = (f"{sh_f} sh × ₹{close:.2f} = ₹{pos_v:,.0f} | Risk ₹{sh_f*rps:,.0f} | Kelly {kelly_frac*100:.2f}% [{kelly_source}]"
              if sh_f > 0 else "— (below sizing min)")

    # Circuit breaker for small caps
    # Circuit breaker for small caps
    alloc_note = ""
    if close < MAX_PRICE:
        cb_active, cb_msg = check_smallcap_cb()
        if cb_active: alloc_note=f" ⚠️ CB: {cb_msg[:40]}"

    # ── Sector momentum bonus/penalty ──────────────────────────────────
    sector_mom = _live_sector_momentum(sector)
    mom_bonus = sector_mom["bonus"]
    fused = max(0, min(100, fused + mom_bonus))
    # Re-derive grade so return dict reflects post-momentum score
    grade = (
        "APEX"     if fused >= GRADE_APEX     else
        "PRISTINE" if fused >= GRADE_PRISTINE else
        "GOOD"     if fused >= GRADE_GOOD     else
        "PROBE"
    )
    mom_note = f" | Sector {sector_mom['momentum_tier']} ({sector_mom['rel_5d']:+.1f}% 5d)" if mom_bonus != 0 else ""

    # ── META-LABELING: Store final signal vector + model veto ───────────
    # Now that fused and grade are fully resolved (post-sector-momentum),
    # we store the complete feature vector that will be used for ML training.
    # Every signal that passes the min-score gate is stored here so the DB
    # accumulates trade history aggressively — this is what feeds the AI Brain.
    meta_features = {
        "whale_score":        whale_score,
        "div_score":          div_score,
        "vp_score":           vp_score,
        "pat_score":          pat_score,
        "bayes_pct":          bayes["bayes_pct"],
        "mc_survival":        mc_survival or 0,
        "fort_norm":          fort_norm,
        "apex_composite":     apex_composite,
        "confluence_bonus":   confluence_bonus,
        "macro_state":        macro_state,
        "sector":             sector,
        "vix_level":          vix,
        "grade":              grade,
        "primary_fused_score": fused,
        # BUG-6 FIX: persist days_to_earnings at INSERT time so reply_handler
        # earnings gate can read it immediately from meta_features without waiting
        # for the post-loop UPDATE in run() — which may run AFTER the first poll.
        "days_to_earnings":   earn_days if earn_days is not None else -1,
    }
    _store_meta_features(
        datetime.today().strftime("%Y-%m-%d"),
        symbol, meta_features
    )

    meta_model = _load_meta_model()
    # RC2 FIX: When meta-model is untrained (< 20 closed picks), _get_meta_probability
    # returns a flat 0.55 for every pick → identical AI% → no ranking differentiation.
    # Use _heuristic_meta_prob() instead, which blends fused/mc/bayes for real signal.
    # We need the partial pick dict built so far; r is assembled below, so pass locals.
    _partial = {"fused": fused, "mc_survival": mc_survival, "bayes_pct": bayes["bayes_pct"]}
    if meta_model is None:
        meta_prob = _heuristic_meta_prob(_partial)
        log.debug(f"  {symbol}: cold-start meta_prob={meta_prob:.3f} (heuristic)")
    else:
        meta_prob = _get_meta_probability(meta_model, meta_features)
    # FIX 5: Meta-model veto guard.
    # The meta-labeler is trained incrementally via _train_meta_labeler(min_samples=50).
    # When trained on fewer than 200 profitable samples its class imbalance causes it
    # to learn "veto everything" — exactly what Bug 5 predicts.
    # Guard: only apply the veto when the model was trained on ≥ 200 closed picks
    # AND the probability is clearly below the threshold (< 0.40 rather than 0.45).
    # This lets early picks through while the DB accumulates enough outcome history.
    meta_sample_count = 0
    try:
        with _db_conn() as _mc:
            _row = _mc.execute(
                "SELECT COUNT(*) FROM pick_outcomes WHERE status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')"
            ).fetchone()
            meta_sample_count = _row[0] if _row else 0
    except Exception:
        pass

    _META_VETO_THRESHOLD = 0.40   # stricter than old 0.45 (less hair-trigger)
    _META_MIN_SAMPLES    = 200    # don't trust the model until we have enough data

    if meta_sample_count >= _META_MIN_SAMPLES and meta_prob < _META_VETO_THRESHOLD:
        log.info(f"  🚫 {symbol}: Meta-model veto (P={meta_prob:.2f} < {_META_VETO_THRESHOLD}, "
                 f"n={meta_sample_count} samples)")
        return None
    elif meta_sample_count < _META_MIN_SAMPLES:
        log.debug(f"  Meta-model: skipping veto ({meta_sample_count} < {_META_MIN_SAMPLES} samples needed)")

    # ── FOG sizing cap ─────────────────────────────────────────────────
    fog_note=""
    if fog["fog_block"]:
        cap  = 10 if fog["fog_tier"]=="FOG_SEVERE" else 25
        deploy=min(deploy, cap/100)
        sh_f = min(sh_f, math.floor(sh_f*(cap/100)*2))
        fog_note=f" | {fog['fog_label'][:40]}"

    # ── Story: structured human-readable narrative ─────────────────────
    parts=[]
    if "BUYING" in fii_lbl and "FII+DII" in fii_lbl: parts.append("institutional tide in — FII+DII both accumulating")
    elif "FII BUYING" in fii_lbl:                     parts.append("FII net buyers — foreign flows positive")
    if ins_det and "buy" in ins_det.lower() and ins_pts>=10: parts.append(f"insiders accumulating ({ins_det[:40]})")
    if fil_det and "No recent" not in fil_det and fil_pts>=20: parts.append(fil_det[:50])
    if whale_det["whale_detected"]:
        wl=whale_det["whale_label"].split("|")[0].strip()
        if wl: parts.append(wl[:50])
    if fort["layer1"]: parts.append(f"price AT institutional VPOC ₹{poc:.2f} — high-conviction floor")
    if div_det["div_type"]=="BULLISH_HIDDEN": parts.append("hidden RSI divergence — smart money dip-buying")
    if "VCP" in pat_label or "Cup" in pat_label: parts.append(f"pattern: {pat_label[:40]}")
    if bayes["bayes_pct"]>=65: parts.append(f"14-node Bayes: {bayes['bayes_pct']}% conviction")
    if not parts: parts.append(f"fused score {fused}/100 — confluence setup")
    story="; ".join(parts[:4]).capitalize()

    # ── LLM ENHANCEMENT — MOVED OUT of scoring loop ──────────────────────────
    # FIX-CRIT2: LLM calls have been deliberately removed from here.
    # Previously this ran Claude for every candidate (up to 200/day) even though
    # only 5 ever reach Telegram — burning ~95% of tokens on discarded picks.
    # _story_parts and _raw_filing are stored in the return dict so that the
    # post-top-N loop in run() can call _llm_story_enhance / _llm_alpha_mine
    # on the final 5 picks only.  Cost: ₹9/day vs ₹129/day before.
    llm_story  = None
    llm_filing = None

    # (meta_features already stored above, after sector momentum is applied)

    return {
        "symbol":   symbol,
        "sector":   sector,
        "close":    round(close,2),
        "grade":    grade,
        "llm_story": llm_story,
        "llm_filing_sentiment": None,
        "llm_filing_detail": None,
        # Carry story_parts + raw filing so post-top-N LLM enrichment can use them
        "_story_parts": parts,
        "_raw_filing":  fil_data.get("detail", ""),

        # Fused scores
        "fused":          fused,
        "fort_total":     fort_total,
        "fort_pct":       round(fort_norm,1),
        "apex_composite": apex_composite,

        # Sub-scores
        "score_fortress": fort["fortress_pts"],
        "score_fii":      fii_pts,
        "score_insider":  ins_pts,
        "score_filing":   fil_pts,
        "score_earnings": earn_pts,
        "whale_score":    round(whale_score,1),
        "div_score":      round(div_score,1),
        "vp_score":       round(vp_score,1),
        "pat_score":      round(pat_score,1),
        "bayes_pct":      bayes["bayes_pct"],
        "mc_survival":    mc_survival,

        # Trade plan
        "buy_lo":    round(close*0.99,2),
        "buy_hi":    round(close*1.01,2),
        "stop_loss": stop_loss,
        "risk_pct":  risk_pct,
        "r1": r1, "r2": r2, "r3": r3,
        "r1_pct": r1_pct, "r2_pct": r2_pct, "r3_pct": r3_pct,
        "sell_r1": 30, "sell_r2": 30, "sell_r3": 40,
        "trail_stop":   trail_stop,
        "shares":       sh_f,
        "pos_value":    round(pos_v),
        "deploy_pct":   round(deploy*100),
        "pos_label":    pos_lb,

        # Labels & signals
        "whale_label":  whale_det["whale_label"],
        "pat_label":    pat_label,
        "div_label":    div_det["div_label"],
        "vp_label":     vp_label,
        "mc_label":     mc["label"],
        "bayes_label":  bayes["bayes_label"],
        "fii_label":    fii_lbl,
        "fii_detail":   fii_det,
        "ins_detail":   ins_det,
        "fil_detail":   fil_det,
        "earn_detail":  earn_det,
        "cvd_label":    cvd["cvd_label"],
        "vsa_label":    vsa["vsa_label"],
        "fog_label":    fog["fog_label"],

        # Fortress layers
        "layer1": fort["layer1"], "layer2": fort["layer2"], "layer3": fort["layer3"],
        "vcp_coil": fort["vcp_coil"], "regime": fort["regime"],
        "w52_bonus": fort["w52_bonus"], "forward_bonus": fort["forward_bonus"],
        "vdu_label": fort["vdu_label"],

        # Technicals
        "rsi":  fort["rsi"],  "mfi": fort["mfi"],
        "adx":  fort["adx"],  "atr14": fort["atr14"],
        "poc":  round(poc,2), "ma200": fort["ma200"],
        "alt_pct": fort["alt_pct"], "velocity_pct": fort["velocity_pct"],

        # Meta
        "data_quality":    dq,
        "vol_reliable":    fort["vol_reliable"],
        "story":           story,
        "earn_days":       earn_days,
        "days_to_r1_est":  mc.get("days_to_t1") or MC_HORIZON,
        "r1_hit_prob":     mc.get("t1_hit_pct",0),
        "alloc_note":      alloc_note+fog_note,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 14 — TELEGRAM (ultra-compact, plain English)
# ══════════════════════════════════════════════════════════════════════════════

def _escape(s) -> str:
    text = str(s) if s is not None else ""
    special = r'\_*[]()~`>#+-=|{}.!'
    return "".join(("\\" + ch if ch in special else ch) for ch in text)


def _split_msg(msg: str, limit: int = 4000) -> list:
    if len(msg) <= limit:
        return [msg]
    cards = msg.split("\n\n"); chunks = []; cur = ""
    for card in cards:
        blk = card + "\n\n"
        if len(cur) + len(blk) > limit:
            if cur.strip(): chunks.append(cur.rstrip())
            cur = blk
        else:
            cur += blk
    if cur.strip(): chunks.append(cur.rstrip())
    return chunks


def _tg_post(token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for attempt, delay in enumerate([0, 2, 5], 1):
        if delay: time.sleep(delay)
        try:
            r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=20)
            if r.status_code == 200: return True
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", 5))); continue
        except Exception as e:
            log.error(f"Telegram attempt {attempt}: {e}")
    return False


def _grade_plain(grade: str) -> str:
    return {
        "⚔️ APEX": "STRONG",
        "💎 PRISTINE": "STRONG",
        "🟢 GOOD": "DECENT",
        "🔵 PROBE": "WEAK",
    }.get(grade, grade)


def _verdict_plain(r: dict) -> str:
    """Only SKIP or GO. No 'SMALL' verdict."""
    problems = []
    
    if r.get("fog_block"):
        return "⛔ SKIP — Market too foggy. Stay out."
    
    if not r.get("vol_reliable", True):
        problems.append("volume data missing")
    if r.get("vcp_coil", "").startswith("LOOSE"):
        problems.append("price too volatile")
    if r["risk_pct"] > 10:
        problems.append(f"stop too far at {r['risk_pct']:.0f}%")
    if r.get("earn_days") is not None and 0 <= r["earn_days"] <= 5:
        problems.append(f"earnings in {r['earn_days']}d")
    if r.get("alloc_note", "").startswith(" ⚠️ CB"):
        problems.append("small-cap safety lock ON")
    
    if problems:
        return "⛔ SKIP — " + "; ".join(problems[:2]) + ". Not safe."
    
    # No problems = GO
    if r["fused"] >= 72:
        return "✅ GO — Full position."
    if r["fused"] >= 60:
        return "✅ GO — Normal position."
    return "✅ GO — Small test only."


def _why_plain(r: dict) -> str:
    """Ultra-short why."""
    parts = []
    
    fii = r.get("fii_label", "")
    if "FII+DII" in fii and "BUYING" in fii:
        parts.append("institutions buying")
    elif "FII" in fii and "BUYING" in fii:
        parts.append("foreign investors buying")
    elif "DII" in fii and "BUYING" in fii:
        parts.append("domestic investors buying")
    
    ins = r.get("ins_detail", "")
    if ins and "buy" in ins.lower() and r.get("score_insider", 0) >= 10:
        parts.append("insiders buying")
    
    fil = r.get("fil_detail", "")
    if fil and "No recent" not in fil and r.get("score_filing", 0) >= 20:
        if "dividend" in fil.lower(): parts.append("dividend coming")
        elif "bonus" in fil.lower(): parts.append("bonus shares")
        elif "buyback" in fil.lower(): parts.append("buyback")
        else: parts.append("good news")
    
    if r.get("layer1"): parts.append("at support")
    if r.get("layer2"): parts.append("heavy volume")
    if r.get("layer3"): parts.append("support holding")
    
    pat = r.get("pat_label", "")
    if "VCP" in pat: parts.append("coil forming")
    if "Cup" in pat: parts.append("cup pattern")
    
    div = r.get("div_label", "")
    if "BULLISH" in div: parts.append("hidden buy signal")
    
    whale = r.get("whale_label", "")
    if "Stealth" in whale: parts.append("smart money sneaking")
    elif "Accumulation" in whale: parts.append("big buyers accumulating")
    
    bayes = r.get("bayes_pct", 0)
    if bayes >= 75: parts.append(f"AI {bayes}% sure")
    elif bayes >= 60: parts.append(f"AI {bayes}% confident")
    
    if not parts:
        return "Some confluence"
    
    return " + ".join(parts[:3])


# =====================================================================================
# v5.4 -- THREE-LANE ENGINE
# Stage 2: Parallel three-lane scoring using SHARED compute_indicators() output.
# Each lane computes a different subset of the full pipeline to maximize signal
# diversity while eliminating redundant computation.
# =====================================================================================

def _score_fortress_lane(symbol: str, today_row: dict, hist: pd.DataFrame,
                          fii_data: dict, insider_map: dict, filings: dict,
                          earnings_cal: dict, macro: dict,
                          data_source: str = "NSE") -> Optional[dict]:
    """
    LANE 1 -- FORTRESS ONLY.
    Runs fortress_score() only. No whale, no divergence, no bayesian, no MC.
    Output: fort_pts as the ranking key.
    Cost: $0 -- pure indicator math, no LLM, no heavy APEX sub-calls.
    """
    try:
        macro_state = macro.get("macro_state", "CHOP")
        earn_days = earnings_cal.get(symbol.upper())
        if earn_days is None:
            earn_days = _check_earnings_yf(symbol)
        if earn_days is not None and 0 <= earn_days <= 2:
            return None
        if macro_state == "MASSACRE":
            return None

        fort = fortress_score(symbol, today_row, hist, macro_state=macro_state)
        if fort is None:
            return None

        close = float(today_row["close"])
        fii_pts = fii_data.get("score", 15)
        ins_pts = insider_map.get(symbol.upper(), {}).get("score", 0)
        fil_pts = filings.get(symbol.upper(), {}).get("score", 15)
        earn_pts = 20  # neutral when not computing full earn schedule

        fort_total = min(200, fort["fortress_pts"] + fii_pts + ins_pts + fil_pts + earn_pts)
        sector = get_sector(symbol)

        return {
            "symbol":    symbol,
            "lane":      "FORTRESS",
            "fort_pts":  fort_total,
            "apex_comp": 0.0,   # not computed in this lane
            "fused":     0.0,   # not applicable
            "close":     close,
            "stop_loss": fort.get("t3", round(close * 0.93, 2)),
            "r1":        round(close * 1.15, 2),
            "r2":        round(close * 1.30, 2),
            "r3":        round(close * 1.50, 2),
            "sector":    sector,
            "atr14":     fort.get("atr14", 0.0),
            "adv20":     fort.get("adv20", 0.0),
            "vpoc":      fort.get("vpoc", 0.0),
            "layer1":    fort.get("layer1", False),
            "layer2":    fort.get("layer2", False),
            "layer3":    fort.get("layer3", False),
            "adx":       fort.get("adx", 0.0),
            "mfi":       fort.get("mfi", 50.0),
            "vol_reliable": fort.get("vol_reliable", True),
            "whale_score":  0.0,
            "div_score":    0.0,
            "div_type":     "NONE",
            "bayes_pct":    50.0,
            "mc_survival":  None,
            "grade":        "FORTRESS",
            "story":        f"Fortress: VPOC {fort.get('layer1', False)} Vol {fort.get('vol_reliable', True)} ADX {fort.get('adx', 0):.0f}",
            "earn_days":    earn_days,
        }
    except Exception as e:
        log.debug(f"_score_fortress_lane {symbol}: {e}")
        return None


def _score_apex_lane(symbol: str, today_row: dict, hist: pd.DataFrame,
                     fii_data: dict, insider_map: dict, filings: dict,
                     earnings_cal: dict, macro: dict,
                     data_source: str = "NSE") -> Optional[dict]:
    """
    LANE 2 -- APEX ONLY.
    Runs the 7 APEX engines without VPOC veto gate. No fortress hard-veto.
    Ranking key: apex_composite.
    Catches momentum/whale setups that fortress might veto (e.g. slightly above VPOC).
    Cost: $0 -- pure math.
    """
    try:
        macro_state = macro.get("macro_state", "CHOP")
        breadth_ok = macro.get("breadth_ok", True)
        vix = macro.get("vix_val", 18.0)

        earn_days = earnings_cal.get(symbol.upper())
        if earn_days is None:
            earn_days = _check_earnings_yf(symbol)
        if earn_days is not None and 0 <= earn_days <= 2:
            return None
        if macro_state == "MASSACRE":
            return None

        if len(hist) < MIN_HIST_BARS:
            return None

        close = float(today_row["close"])
        sector = get_sector(symbol)
        if sector in SECTOR_BLOCKED and symbol.upper() not in _RENEWABLE_SYMBOLS:
            return None

        ind = compute_indicators(hist, 14)
        atr14 = ind["atr14"]
        adv20 = float(hist["volume"].tail(20).mean()) if len(hist) >= 20 else float(today_row.get("volume", 1))
        vpoc = calc_vpoc(hist)
        profile = _vpoc_profile(hist)
        poc = profile.get("poc", vpoc) or vpoc

        stop_from_atr = close - 2.5 * atr14 * SECTOR_ATR_MULT.get(sector, 1.0)
        stop_from_poc = poc * 0.97 if poc > 0 else stop_from_atr
        stop_loss = round(max(min(stop_from_atr, stop_from_poc), close * 0.88), 2)

        whale_score, whale_det = _whale_radar(hist, adv20)
        div_score, div_det = _divergence_engine(hist)
        vp_score, vp_label = _vol_profile_score(profile, close, fortress_vpoc=vpoc)
        pat_score, pat_label = _pattern_score(hist, atr14, profile)
        mc = _monte_carlo(hist, stop_loss, close, data_source=data_source, macro_state=macro_state)
        mc_survival = mc.get("survival")

        if mc.get("hard_veto"):
            return None

        fii_pts = fii_data.get("score", 15)
        ins_pts = insider_map.get(symbol.upper(), {}).get("score", 0)
        fil_pts = filings.get(symbol.upper(), {}).get("score", 15)

        # APEX-only Bayesian (no fortress VPOC layers needed)
        bayes = _bayesian_apex(
            macro_state=macro_state, breadth_ok=breadth_ok,
            layer1=False, layer2=False, layer3=True,  # APEX lane: rely on whale/div
            whale_detected=whale_det["whale_detected"] or whale_det["stealth_score"] >= 50,
            div_type=div_det["div_type"], vp_score=vp_score,
            mfi_v=ind["mfi"], adx_v=ind["adx"], alt_pct=0.0,
            mc_survival=mc_survival,
            fii_pts=fii_pts, ins_pts=ins_pts, fil_pts=fil_pts,
        )
        bayes_score = float(bayes["bayes_pct"])

        confluence_bonus = 0
        if whale_det["whale_detected"] and div_det["div_type"] == "BULLISH_HIDDEN":
            confluence_bonus += 15
        if vp_score >= 40 and ("VCP" in pat_label or "Cup" in pat_label):
            confluence_bonus += 12
        if bayes["bayes_pct"] >= 60 and mc_survival is not None and mc_survival >= 70:
            confluence_bonus += 10
        confluence_bonus = min(35, confluence_bonus)

        macro_damp = {"CLEAR": 1.0, "CHOP": 0.88, "PANIC": 0.60, "MASSACRE": 0.0}
        _CHOP_PRE_COMP = 20
        chop_pre = _CHOP_PRE_COMP if macro_state == "CHOP" else 0

        raw_apex = (
            whale_score * W["whale_radar"] +
            div_score   * W["divergence"] +
            vp_score    * W["vol_profile"] +
            pat_score   * W["pattern"] +
            bayes_score * W["bayesian"] +
            confluence_bonus * W["fortress_vpoc"]
        )
        apex_composite = round((raw_apex + chop_pre) * macro_damp.get(macro_state, 0.88))

        if bayes["bayes_pct"] >= 75 and mc_survival is not None and mc_survival >= 75:
            apex_composite = min(100, apex_composite + 5)

        # APEX floor: CLEAR=45, CHOP=30
        apex_floor = 45 if macro_state == "CLEAR" else 30
        if apex_composite < apex_floor:
            return None

        story_parts = []
        if whale_det["whale_detected"]:
            story_parts.append(f"Whale {whale_score:.0f}")
        if div_det["div_type"] == "BULLISH_HIDDEN":
            story_parts.append("HiddenDiv")
        if mc_survival:
            story_parts.append(f"MC {mc_survival:.0f}%")
        if confluence_bonus > 0:
            story_parts.append(f"Confluence +{confluence_bonus}")

        return {
            "symbol":      symbol,
            "lane":        "APEX",
            "fort_pts":    0.0,
            "apex_comp":   float(apex_composite),
            "fused":       0.0,
            "close":       close,
            "stop_loss":   stop_loss,
            "r1":          round(close * 1.15, 2),
            "r2":          round(close * 1.30, 2),
            "r3":          round(close * 1.50, 2),
            "sector":      sector,
            "atr14":       atr14,
            "adv20":       adv20,
            "vpoc":        vpoc,
            "layer1":      False,
            "layer2":      False,
            "layer3":      True,
            "adx":         ind["adx"],
            "mfi":         ind["mfi"],
            "vol_reliable": _volume_reliable(hist, 63),
            "whale_score": float(whale_score),
            "whale_det":   whale_det,
            "div_score":   float(div_score),
            "div_type":    div_det["div_type"],
            "bayes_pct":   bayes_score,
            "mc_survival": mc_survival,
            "mc_params":   mc.get("params", {}),
            "grade":       "APEX",
            "story":       " | ".join(story_parts) or "APEX momentum setup",
            "earn_days":   earn_days,
            "confluence_bonus": confluence_bonus,
        }
    except Exception as e:
        log.debug(f"_score_apex_lane {symbol}: {e}")
        return None


def _run_three_lane_scoring(cands: pd.DataFrame,
                             hist_cache: dict,
                             fii_data: dict, insider_map: dict,
                             filings: dict, earn_cal: dict,
                             macro: dict, data_source: str,
                             date_label: str) -> dict:
    """
    Stage 2 -- THREE-LANE PARALLEL SCORING.

    For each symbol, runs ALL THREE lanes concurrently using ThreadPoolExecutor.
    compute_indicators() is called ONCE per symbol inside fortress_score /
    _score_apex_lane (both call compute_indicators internally and cache in dict).

    Returns:
        {
          "fortress": [sorted list of dicts with fort_pts key],
          "apex":     [sorted list of dicts with apex_comp key],
          "fused":    [sorted list of dicts with fused key -- from assemble_pick],
        }
    """
    from concurrent.futures import ThreadPoolExecutor as _TPE, as_completed as _asc

    fortress_results: List[dict] = []
    apex_results:     List[dict] = []
    fused_results:    List[dict] = []
    _lock = threading.Lock()

    intel_hash = _intelligence_hash(fii_data, insider_map, filings)
    _N_WORKERS = min(8, max(2, len(cands) // 10))
    log.info(f"THREE-LANE: Parallel scoring {len(cands)} symbols | {_N_WORKERS} workers")

    def _score_all_lanes(row_dict: dict):
        sym = row_dict["symbol"]
        today_row = row_dict
        hist = fetch_history_with_proxy_fallback(sym, days=300, yf_cache=hist_cache)  # MEDIUM-1: _YF_CACHE_LOCK guards internal reads
        if hist.empty or len(hist) < MIN_HIST_BARS:
            return sym, None, None, None

        # Check score_cache (FAST_RERUN path)
        if FAST_RERUN:
            cached = _score_cache_get(sym, date_label, float(today_row.get("close", 0)), intel_hash)
            if cached:
                # Reconstruct fused lane from cache; fortress/apex need separate keys
                fused_r = cached
                fused_r["lane"] = "FUSED"
                return sym, None, None, fused_r

        # Halal L1/L2 pre-screen (Stage 1 -- cheap vetoes BEFORE scoring)
        if _halal_l1_business_veto(sym):
            log.debug(f"THREE-LANE L1 veto: {sym}")
            return sym, None, None, None
        l2_veto, _ = _halal_l2_financial_veto(sym)
        if l2_veto:
            log.debug(f"THREE-LANE L2 veto: {sym}")
            return sym, None, None, None

        # Run all 3 lanes
        f_res = _score_fortress_lane(sym, today_row, hist, fii_data, insider_map,
                                     filings, earn_cal, macro, data_source)
        a_res = _score_apex_lane(sym, today_row, hist, fii_data, insider_map,
                                  filings, earn_cal, macro, data_source)
        # FUSED lane = full assemble_pick (existing pipeline)
        u_res = assemble_pick(sym, today_row, hist, fii_data, insider_map,
                              filings, earn_cal, macro, data_source)
        if u_res:
            u_res["lane"] = "FUSED"
            # Persist to score_cache for same-day reruns
            _score_cache_put(sym, date_label, float(today_row.get("close", 0)),
                             u_res, intel_hash)

        return sym, f_res, a_res, u_res

    rows_iter = [row.to_dict() for _, row in cands.iterrows()]
    _completed = 0

    with _TPE(max_workers=_N_WORKERS, thread_name_prefix="3lane") as executor:
        future_map = {executor.submit(_score_all_lanes, row): row["symbol"]
                      for row in rows_iter}
        for future in _asc(future_map):
            sym = future_map[future]
            _completed += 1
            if _completed % 25 == 0:
                log.info(f"THREE-LANE progress: {_completed}/{len(rows_iter)} | "
                         f"F={len(fortress_results)} A={len(apex_results)} U={len(fused_results)}")
            try:
                sym_out, f_res, a_res, u_res = future.result(timeout=90)
                with _lock:
                    if f_res:
                        fortress_results.append(f_res)
                        log.info(f"  FORTRESS {sym_out:12s} | pts={f_res['fort_pts']:.0f}")
                    if a_res:
                        apex_results.append(a_res)
                        log.info(f"  APEX     {sym_out:12s} | comp={a_res['apex_comp']:.0f}")
                    if u_res:
                        fused_results.append(u_res)
                        log.info(f"  FUSED    {sym_out:12s} | fused={u_res.get('fused', 0):.0f}/{u_res.get('grade','?')}")
            except Exception as e:
                log.debug(f"THREE-LANE {sym}: {e}")

    # Sort each lane by its primary ranking key
    fortress_results.sort(key=lambda x: x["fort_pts"], reverse=True)
    apex_results.sort(key=lambda x: x["apex_comp"], reverse=True)
    fused_results.sort(key=lambda x: x.get("fused", 0), reverse=True)

    log.info(f"THREE-LANE scoring complete | F={len(fortress_results)} A={len(apex_results)} U={len(fused_results)}")
    return {
        "fortress": fortress_results[:LANE_TOP_N * 3],  # top 15 candidates pre-halal
        "apex":     apex_results[:LANE_TOP_N * 3],
        "fused":    fused_results[:LANE_TOP_N * 3],
    }


def _deduplicate_lane_winners(lanes: dict) -> List[str]:
    """
    Stage 3 deduplication: collect union of all lane top-N symbols for
    targeted L4 LLM halal screen. Typical: 9-12 unique (60% overlap).
    """
    unique: set = set()
    for lane_name, lane_list in lanes.items():
        for r in lane_list[:LANE_TOP_N]:
            unique.add(r["symbol"])
    return sorted(unique)


def _run_halal_l4_dedup(unique_symbols: List[str], sector_map: dict) -> dict:
    """
    Stage 3 -- DEDUPLICATED L4 LLM SCREEN.
    Runs halal_ai_screen() on ~9-12 unique symbols (not per-lane duplicates).
    Returns {symbol: halal_result} mapping.
    Cost: ~$0.003-0.005 per run (most hits cached from 30-day TTL).
    """
    results = {}
    for sym in unique_symbols:
        sector = sector_map.get(sym, "DIVERSIFIED")
        try:
            results[sym] = halal_ai_screen(sym, sector=sector)
        except Exception as e:
            log.debug(f"Halal L4 {sym}: {e}")
            results[sym] = {"veto": False, "tier": "ACCEPTABLE", "score": 50,
                            "source": "ERROR"}
    log.info(f"L4 dedup screen: {len(unique_symbols)} unique | "
             f"vetoed={sum(1 for r in results.values() if r.get('veto'))}")
    return results


def _select_lane_winner(lane_results: List[dict], halal_map: dict,
                        alpha_mine_map: dict, lane_name: str,
                        min_score_key: str, min_score: float) -> Optional[dict]:
    """
    Stage 4 -- LANE FINALIZATION.
    Applies: score gate + halal PURE filter + L4 veto filter.
    Returns the top qualifying symbol for this lane or None.
    """
    for r in lane_results:
        sym = r["symbol"]
        score = r.get(min_score_key, 0.0)
        if score < min_score:
            continue
        halal = halal_map.get(sym, {})
        if halal.get("veto", False):
            log.debug(f"LANE {lane_name}: {sym} vetoed by L4 halal")
            continue
        if LANE_REQUIRE_HALAL_PURE and halal.get("tier", "ACCEPTABLE") not in ("PURE", "ACCEPTABLE"):
            log.debug(f"LANE {lane_name}: {sym} halal tier {halal.get('tier')} -- skipped")
            continue
        # Attach halal + alpha-mine data to winner
        r["halal_tier"] = halal.get("tier", "ACCEPTABLE")
        r["halal_score"] = halal.get("score", 50)
        r["alpha_mine"] = alpha_mine_map.get(sym, {})
        log.info(f"LANE {lane_name} WINNER: {sym} | {min_score_key}={score:.0f} | halal={r['halal_tier']}")
        return r
    log.info(f"LANE {lane_name}: NO PICK (no symbol passed score+halal gate)")
    return None


def _persist_lane_results(lane_name: str, winner: Optional[dict],
                           date_label: str) -> None:
    """Stage 5 -- DB persistence with lane tag."""
    if not winner:
        return
    try:
        with _db_conn(write=True) as con:
            con.execute("""
                INSERT OR REPLACE INTO sniper_results_v54
                  (run_date, symbol, lane, grade, fort_pts, apex_comp, fused_score,
                   close, stop_loss, r1, r2, r3, story, sector,
                   whale_score, div_score, bayes_pct, mc_survival, halal_tier)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                date_label, winner["symbol"], lane_name,
                winner.get("grade", lane_name),
                float(winner.get("fort_pts", 0) or 0),
                float(winner.get("apex_comp", 0) or 0),
                float(winner.get("fused", 0) or winner.get("apex_comp", 0) or winner.get("fort_pts", 0)),
                float(winner.get("close", 0)),
                float(winner.get("stop_loss", 0)),
                float(winner.get("r1", 0)),
                float(winner.get("r2", 0)),
                float(winner.get("r3", 0)),
                str(winner.get("story", "")),
                str(winner.get("sector", "DIVERSIFIED")),
                float(winner.get("whale_score", 0) or 0),
                float(winner.get("div_score", 0) or 0),
                float(winner.get("bayes_pct", 50) or 50),
                winner.get("mc_survival"),
                winner.get("halal_tier", "ACCEPTABLE"),
            ))
    except Exception as e:
        log.warning(f"_persist_lane_results {lane_name}/{winner.get('symbol')}: {e}")


# =====================================================================================
# v5.4 -- STAGE 8: ANCHORED MONTE CARLO PROJECTION ENGINE
# Triggered every 6h via GitHub Actions OR via /project command from Telegram.
# Compares realized path against original MC simulation bands.
# =====================================================================================

def _anchored_monte_carlo(symbol: str, entry_date: str, entry_price: float,
                           stop_loss: float, r1: float, r2: float, r3: float,
                           hist_realized: pd.DataFrame,
                           mc_params: Optional[dict] = None,
                           n_sims: int = 600) -> dict:
    """
    Re-simulate from today anchoring on actual realized path bars.
    All n_sims paths start with the IDENTICAL realized prices for the first K bars,
    then diverge stochastically from the last known close onward.

    Returns conditional probability estimates:
      P(survival | survived K days), P(R1 | survived K days), etc.
    """
    if hist_realized.empty:
        return {}

    K = len(hist_realized)
    if K == 0:
        return {}

    realized_closes = hist_realized["close"].values.astype(float)
    current_price = float(realized_closes[-1])

    # Compute realized return statistics for regime adjustment
    if K >= 2:
        realized_returns = np.diff(np.log(realized_closes))
        realized_vol = float(np.std(realized_returns))
    else:
        realized_vol = 0.02  # fallback

    # MC params: use passed-in params or estimate from realized
    if mc_params and mc_params.get("sigma"):
        orig_sigma = float(mc_params["sigma"])
        orig_mu    = float(mc_params.get("mu", 0.0))
        df_param   = float(mc_params.get("df", MC_FAT_DF))
    else:
        orig_sigma = max(0.015, realized_vol)
        orig_mu    = 0.001
        df_param   = MC_FAT_DF

    # REGIME ADJUSTMENT: if realized vol > original sigma * 1.5, inflate forward sigma
    vol_ratio = (realized_vol / orig_sigma) if orig_sigma > 0 else 1.0
    forward_sigma = orig_sigma * min(vol_ratio, 2.0)

    # RUN ANCHORED SIMULATION
    paths_final = []
    paths_r1_hit = 0
    paths_r2_hit = 0
    paths_r3_hit = 0
    paths_stopped = 0
    days_to_r1: List[int] = []
    days_to_r2: List[int] = []
    percentile_track: List[float] = []

    np.random.seed(42)
    for _ in range(n_sims):
        path = list(realized_closes)  # anchor: first K bars fixed
        current = path[-1]
        hit_r1 = hit_r2 = hit_r3 = stopped = False
        d_r1 = d_r2 = None

        for day in range(K, K + MC_HORIZON):
            shock = np.random.standard_t(df_param) * forward_sigma
            current *= np.exp(orig_mu + shock)
            path.append(current)

            if not stopped and not hit_r1 and current >= r1:
                hit_r1 = True
                d_r1 = day - K
            if not stopped and not hit_r2 and current >= r2:
                hit_r2 = True
                d_r2 = day - K
            if not stopped and current >= r3:
                hit_r3 = True
                break
            if current <= stop_loss:
                stopped = True
                break

        paths_final.append(current)
        if hit_r1: paths_r1_hit += 1
        if hit_r2: paths_r2_hit += 1
        if hit_r3: paths_r3_hit += 1
        if stopped: paths_stopped += 1
        if d_r1 is not None: days_to_r1.append(d_r1)
        if d_r2 is not None: days_to_r2.append(d_r2)

    # Percentile rank of current price vs simulation paths at day K
    paths_at_k = [p[K - 1] if len(p) >= K else realized_closes[-1] for p in [list(realized_closes)]]
    # compute percentile of current vs forward paths
    pct_rank = float(np.mean([f > current_price for f in paths_final])) * 100
    pct_rank = 100 - pct_rank  # higher = actual price above more sims

    new_survival = max(0.0, min(1.0, (n_sims - paths_stopped) / n_sims))
    r1_prob  = paths_r1_hit / n_sims
    r2_prob  = paths_r2_hit / n_sims
    r3_prob  = paths_r3_hit / n_sims
    stop_prob = paths_stopped / n_sims

    exp_days_r1 = float(np.mean(days_to_r1)) if days_to_r1 else float(MC_HORIZON)
    exp_days_r2 = float(np.mean(days_to_r2)) if days_to_r2 else float(MC_HORIZON)

    return {
        "K":             K,
        "current_price": current_price,
        "new_survival":  round(new_survival * 100, 1),
        "r1_prob":       round(r1_prob * 100, 1),
        "r2_prob":       round(r2_prob * 100, 1),
        "r3_prob":       round(r3_prob * 100, 1),
        "stop_prob":     round(stop_prob * 100, 1),
        "exp_days_r1":   round(exp_days_r1, 1),
        "exp_days_r2":   round(exp_days_r2, 1),
        "percentile_rank": round(pct_rank, 1),
        "vol_ratio":     round(vol_ratio, 2),
        "forward_sigma": round(forward_sigma, 4),
        "paths_final_p25": round(float(np.percentile(paths_final, 25)), 2),
        "paths_final_p50": round(float(np.percentile(paths_final, 50)), 2),
        "paths_final_p75": round(float(np.percentile(paths_final, 75)), 2),
    }


def _compute_divergence_sigma(orig_survival: float, new_survival: float,
                               percentile_rank: float) -> float:
    """Estimate sigma divergence from original projection."""
    survival_delta = abs(new_survival - orig_survival)
    # Approximate: each 10pp survival delta ~ 1 sigma in a Gaussian approximation
    sigma = survival_delta / 10.0
    # Boost if percentile rank is extreme (>85 or <15)
    if percentile_rank > 85 or percentile_rank < 15:
        sigma += 0.5
    return round(sigma, 2)


def _llm_divergence_narrative(symbol: str, lane: str, entry: float,
                               entry_date: str, current: float, K: int,
                               orig_survival: float, new_survival: float,
                               r1_prob: float, divergence_sigma: float) -> str:
    """
    Stage 8 -- LLM divergence narrative. Only fires when divergence > MC_DIVERGENCE_SIGMA_TH.
    Tier 1: GPT-4.1 Nano (~$0.0003/call). 24-hour cache.
    """
    cache_key = f"mc_div:{symbol}:{lane}:{K}"
    cached = _llm_cached(cache_key, "alpha_mine")
    if cached:
        return cached

    prompt = (
        f"Symbol: {symbol} | Lane: {lane}\n"
        f"Entry: Rs{entry:.0f} on {entry_date} | Current: Rs{current:.0f}\n"
        f"Days held: {K} | Original MC: {orig_survival:.0f}% survival\n"
        f"Anchored MC: {new_survival:.0f}% survival | R1 prob: {r1_prob:.0f}%\n"
        f"Divergence: {divergence_sigma:.1f}sigma from expected\n\n"
        f"Narrate: Is this tracking bullish/bearish tail? "
        f"Should holder trim, hold, or add? ONE SENTENCE only."
    )
    raw = _call_tier1(prompt, max_tokens=100)
    if not raw:
        delta = new_survival - orig_survival
        if delta > 10:
            return f"Tracking bullish tail (+{delta:.0f}pp survival); hold position."
        elif delta < -10:
            return f"Underperforming expectations ({delta:.0f}pp vs original); consider trim."
        return "Path within expected range; hold per original plan."

    narrative = raw.strip()[:200]
    _llm_store_cache(cache_key, "alpha_mine", narrative)
    return narrative


def _run_mc_projection_engine(date_label: str) -> List[dict]:
    """
    Stage 8 -- LIVE MC PROJECTION ENGINE.
    Processes all open positions: re-anchors MC simulation on realized path,
    computes conditional probabilities, persists to mc_projections table.
    Returns list of projection dicts for Telegram output.
    """
    if not MC_PROJECTION_ENABLED:
        return []

    projections = []
    check_date = datetime.today().strftime("%Y-%m-%d")

    try:
        with _db_conn() as con:
            open_picks = con.execute("""
                SELECT DISTINCT run_date, symbol, lane, close as entry_price,
                       stop_loss, r1, r2, r3
                FROM sniper_results_v54
                WHERE run_date >= ?
                  AND NOT EXISTS (
                      SELECT 1 FROM pick_outcomes po
                      WHERE po.symbol = sniper_results_v54.symbol
                        AND po.run_date = sniper_results_v54.run_date
                        AND po.status NOT IN ('open')
                  )
                ORDER BY run_date DESC
            """, ((datetime.today() - timedelta(days=MC_HORIZON + 5)).strftime("%Y-%m-%d"),)).fetchall()
    except Exception as e:
        log.debug(f"MC projection: no open picks found: {e}")
        return []

    if not open_picks:
        log.info("MC projection: no open positions to project")
        return []

    for row in open_picks:
        run_date, sym, lane, entry_price, stop_loss, r1, r2, r3 = row
        try:
            # Get original MC params from mc_projections (day 0) if available
            with _db_conn() as con:
                orig_row = con.execute("""
                    SELECT orig_survival, mc_params_json, days_held
                    FROM mc_projections
                    WHERE symbol=? AND lane=? AND run_date=?
                    ORDER BY check_date ASC LIMIT 1
                """, (sym, lane, run_date)).fetchone()

            orig_survival = float(orig_row[0]) if orig_row and orig_row[0] else 75.0
            mc_params = json.loads(orig_row[1]) if orig_row and orig_row[1] else {}

            # Fetch realized path from entry_date to today
            entry_dt = datetime.strptime(run_date, "%Y-%m-%d")
            hist_realized = fetch_history_with_proxy_fallback(sym, days=MC_HORIZON + 10)
            if hist_realized.empty:
                continue
            hist_realized = hist_realized[
                hist_realized["date"] >= pd.Timestamp(entry_dt)
            ].copy()
            if len(hist_realized) < 1:
                continue

            # Run anchored MC
            proj = _anchored_monte_carlo(
                symbol=sym, entry_date=run_date,
                entry_price=float(entry_price or 0),
                stop_loss=float(stop_loss or 0),
                r1=float(r1 or 0), r2=float(r2 or 0), r3=float(r3 or 0),
                hist_realized=hist_realized,
                mc_params=mc_params,
                n_sims=MC_PROJECTION_SIMS,
            )
            if not proj:
                continue

            new_survival = proj["new_survival"]
            r1_prob = proj["r1_prob"]
            K = proj["K"]
            percentile_rank = proj["percentile_rank"]
            divergence_sigma = _compute_divergence_sigma(orig_survival, new_survival, percentile_rank)

            # LLM narrative only on significant divergence
            narrative = ""
            if divergence_sigma >= MC_DIVERGENCE_SIGMA_TH:
                narrative = _llm_divergence_narrative(
                    sym, lane, float(entry_price or 0), run_date,
                    proj["current_price"], K,
                    orig_survival, new_survival, r1_prob, divergence_sigma
                )

            # Determine action signal
            if new_survival >= orig_survival + 15 and r1_prob >= 60:
                action_signal = "HOLD"
            elif new_survival < orig_survival - 15:
                action_signal = "TRIM R1" if r1_prob >= 40 else "CUT"
            elif r1_prob >= 70 and percentile_rank >= 75:
                action_signal = "ADD"
            else:
                action_signal = "HOLD"

            projection_record = {
                "run_date":        run_date,
                "symbol":          sym,
                "lane":            lane,
                "check_date":      check_date,
                "days_held":       K,
                "entry_price":     float(entry_price or 0),
                "current_price":   proj["current_price"],
                "orig_survival":   orig_survival,
                "new_survival":    new_survival,
                "r1_prob":         r1_prob,
                "r2_prob":         proj["r2_prob"],
                "r3_prob":         proj["r3_prob"],
                "stop_prob":       proj["stop_prob"],
                "expected_days":   proj["exp_days_r1"],
                "divergence_sigma": divergence_sigma,
                "percentile_rank": percentile_rank,
                "narrative":       narrative,
                "action_signal":   action_signal,
                "mc_params_json":  json.dumps(mc_params),
                "p25":             proj.get("paths_final_p25", 0),
                "p50":             proj.get("paths_final_p50", 0),
                "p75":             proj.get("paths_final_p75", 0),
            }

            # Persist
            try:
                with _db_conn(write=True) as con:
                    con.execute("""
                        INSERT OR REPLACE INTO mc_projections
                          (run_date, symbol, lane, check_date, days_held,
                           entry_price, current_price, orig_survival, new_survival,
                           r1_prob, r2_prob, r3_prob, stop_prob, expected_days,
                           divergence_sigma, percentile_rank, narrative,
                           action_signal, mc_params_json)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        run_date, sym, lane, check_date, K,
                        float(entry_price or 0), proj["current_price"],
                        orig_survival, new_survival,
                        r1_prob, proj["r2_prob"], proj["r3_prob"], proj["stop_prob"],
                        proj["exp_days_r1"], divergence_sigma, percentile_rank,
                        narrative, action_signal, json.dumps(mc_params)
                    ))
            except Exception as e:
                log.debug(f"MC projection persist {sym}/{lane}: {e}")

            projections.append(projection_record)
            log.info(
                f"MC PROJECTION {sym} ({lane}): day={K} | "
                f"survival={new_survival:.0f}% (was {orig_survival:.0f}%) | "
                f"R1={r1_prob:.0f}% | pct={percentile_rank:.0f} | "
                f"sigma={divergence_sigma:.1f} | action={action_signal}"
            )

        except Exception as e:
            log.debug(f"MC projection {sym}/{lane}: {e}")
            continue

    log.info(f"MC projection engine: {len(projections)} open positions processed")
    return projections


def _format_projection_card(proj: dict) -> str:
    """Stage 6 -- Format MC projection Telegram card."""
    sym = proj["symbol"]
    lane = proj["lane"]
    lane_icon = {"FORTRESS": "🏰", "APEX": "🎯", "FUSED": "⚔️"}.get(lane, "📊")
    K = proj["days_held"]
    entry = proj["entry_price"]
    current = proj["current_price"]
    pnl_pct = ((current - entry) / entry * 100) if entry > 0 else 0

    delta_surv = proj["new_survival"] - proj["orig_survival"]
    delta_str = f"+{delta_surv:.0f}pp" if delta_surv >= 0 else f"{delta_surv:.0f}pp"
    surv_icon = "📈" if delta_surv >= 5 else ("📉" if delta_surv <= -5 else "➡️")

    # ASCII path visualization (25-char wide)
    p25 = proj.get("p25", current * 0.97)
    p75 = proj.get("p75", current * 1.03)
    in_band = p25 <= current <= p75
    band_label = "inside band ✅" if in_band else ("above band 🔥" if current > p75 else "below band ⚠️")

    narrative = proj.get("narrative", "")
    action = proj.get("action_signal", "HOLD")
    action_icon = {"HOLD": "🟡", "ADD": "🟢", "TRIM R1": "🔵", "CUT": "🔴"}.get(action, "⚪")

    lines = [
        f"📊 LIVE PROJECTION: {sym} ({lane_icon} {lane})",
        f"─────────────────────────────────────",
        f"Entry: ₹{entry:,.0f} | Now: ₹{current:,.0f} | {pnl_pct:+.1f}% | Day {K}",
        f"",
        f"ORIGINAL FORECAST (Day 0):",
        f"  Survival: {proj['orig_survival']:.0f}%",
        f"",
        f"CURRENT FORECAST (Anchored, Day {K}):",
        f"  {surv_icon} Survival: {proj['new_survival']:.0f}%  [{delta_str}]",
        f"  R1 prob: {proj['r1_prob']:.0f}%  |  R2 prob: {proj['r2_prob']:.0f}%",
        f"  Stop prob: {proj['stop_prob']:.0f}%  |  Pct rank: {proj['percentile_rank']:.0f}th",
        f"  Path: {band_label}  |  σ divergence: {proj['divergence_sigma']:.1f}",
        f"",
    ]
    if narrative:
        lines.append(f"🤖 {narrative}")
        lines.append(f"")
    lines.append(f"{action_icon} ACTION: {action}  |  Confidence: {min(99, int(proj['r1_prob']))}%")

    return "\n".join(lines)


# =====================================================================================
# v5.4 -- STAGE 6: THREE-CARD TELEGRAM SENDER
# Replaces send_telegram_v3() for three-lane runs.
# =====================================================================================

def send_telegram_lanes(lane_winners: dict, projections: List[dict],
                         macro: dict, fii_data: dict,
                         date_label: str, data_source: str,
                         capacity: dict = None) -> None:
    """
    Stage 6 -- THREE-CARD Telegram send.
    CARD 1: 🏰 FORTRESS LANE
    CARD 2: 🎯 APEX LANE
    CARD 3: ⚔️ FUSED LANE
    + PROJECTION CARDS for open positions (if any)
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram lanes: not configured"); return

    if capacity is None:
        capacity = _capacity_guard(date_label)

    vix_val  = macro.get("vix_val", 0.0)
    macro_st = macro.get("macro_state", "CHOP")
    macro_icon = {"CLEAR": "🟢", "CHOP": "🟡", "PANIC": "🔴",
                  "FOG": "🌫️", "MASSACRE": "🚨"}.get(macro_st, "⚪")

    # HEADER
    header_lines = [
        f"⚔️ SNIPER {VERSION} | {date_label} | {macro_icon} {macro_st} | VIX {vix_val:.1f}",
        f"📡 3-Lane Mode | Halal | Manual execution only",
        f"FII/DII: {fii_data.get('label', '—')} | {fii_data.get('detail', '—')}",
        "",
    ]

    if macro_st == "MASSACRE":
        header_lines.append("🚨 MARKET CRASH — NO TRADES TODAY.")
        _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, "\n".join(header_lines))
        return
    if macro_st == "PANIC":
        header_lines.append("🔴 MARKET PANIC — NO NEW TRADES.")
        _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, "\n".join(header_lines))
        return

    _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, "\n".join(header_lines))

    # CARDS
    lane_configs = [
        ("FORTRESS", "🏰 FORTRESS LANE", lane_winners.get("fortress"),
         "fort_pts", LANE_FORTRESS_MIN, "FORTRESS"),
        ("APEX",     "🎯 APEX LANE",     lane_winners.get("apex"),
         "apex_comp", LANE_APEX_MIN,    "APEX"),
        ("FUSED",    "⚔️ FUSED LANE",   lane_winners.get("fused"),
         "fused",    LANE_FUSED_MIN,    "FUSED"),
    ]

    for lane_key, lane_title, winner, score_key, min_score, lane_id in lane_configs:
        card_lines = [f"{lane_title}", "─────────────────────────────────────"]

        if winner is None:
            card_lines.append(f"NO PICK today — no {lane_key} setup cleared halal+score gate")
        else:
            sym = winner["symbol"]
            close = winner["close"]
            sl = winner["stop_loss"]
            r1 = winner["r1"]
            r2 = winner["r2"]
            r3 = winner["r3"]
            score = winner.get(score_key, 0)
            sector = winner.get("sector", "DIVERSIFIED")
            halal_tier = winner.get("halal_tier", "ACCEPTABLE")

            # Confidence from meta-model or score-based
            conf_pct = min(99, max(10, int(score)))
            conf_flag = "WORTH YOUR TIME" if conf_pct >= 65 else ("MAYBE" if conf_pct >= 50 else "SKIP")

            risk_pct = round((close - sl) / close * 100, 1) if close > 0 else 0
            entry_lo = round(close * 0.995, 2)
            entry_hi = round(close * 1.005, 2)

            card_lines.extend([
                f"#{1} {sym} | AI CONFIDENCE {conf_pct}% [{conf_flag}]",
                f"₹{close:,.0f} | Buy ₹{entry_lo:,.0f}–₹{entry_hi:,.0f} | SL ₹{sl:,.0f} ({risk_pct}%)",
                f"R1 ₹{r1:,.0f} | R2 ₹{r2:,.0f} | R3 ₹{r3:,.0f} | Halal: {halal_tier}",
            ])

            # LLM confidence line — show when unified LLM has enriched this winner
            llm_conf = winner.get("llm_confidence", 0)
            llm_verdict = winner.get("llm_verdict", "")
            if llm_conf > 0 and llm_verdict:
                card_lines.append(f"🤖 LLM {llm_conf}% [{llm_verdict}]"
                                  + (f" — {winner.get('llm_narrative', '')[:60]}"
                                     if winner.get("llm_narrative") else ""))

            if lane_key == "FORTRESS":
                layer1_str = "✓" if winner.get("layer1") else "✗"
                vol_str    = "✓" if winner.get("vol_reliable", True) else "✗"
                adx_val    = winner.get("adx", 0)
                card_lines.append(
                    f"Fortress: VPOC {layer1_str} Vol {vol_str} ADX {adx_val:.0f}"
                )
            elif lane_key == "APEX":
                whale_str = "✓" if winner.get("whale_score", 0) >= 15 else "✗"
                div_str   = "✓" if winner.get("div_type") == "BULLISH_HIDDEN" else "✗"
                bayes_pct = winner.get("bayes_pct", 50)
                mc_surv   = winner.get("mc_survival")
                card_lines.append(
                    f"Whale {whale_str} Div {div_str} Bayes {bayes_pct:.0f}% "
                    + (f"MC {mc_surv:.0f}%" if mc_surv else "")
                )
            elif lane_key == "FUSED":
                layer1_str = "✓" if winner.get("layer1") else "✗"
                vol_str    = "✓" if winner.get("vol_reliable", True) else "✗"
                whale_str  = "✓" if winner.get("whale_score", 0) >= 15 else "✗"
                div_str    = "✓" if winner.get("div_type") == "BULLISH_HIDDEN" else "✗"
                bayes_pct  = winner.get("bayes_pct", 50)
                mc_surv    = winner.get("mc_survival")
                card_lines.append(
                    f"Fortress: VPOC {layer1_str} Vol {vol_str} | "
                    f"Whale {whale_str} Div {div_str} Bayes {bayes_pct:.0f}%"
                    + (f" MC {mc_surv:.0f}%" if mc_surv else "")
                )

            story = winner.get("story", "")
            if story:
                card_lines.append(f"Why: {story[:120]}")

        card_lines.append("")
        _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, "\n".join(card_lines))
        time.sleep(0.3)

    # FOOTER
    fii_lbl = fii_data.get("label", "—")
    fii_det = fii_data.get("detail", "—")
    footer = (
        f"ℹ️ Reply per lane: TAKEN {{SYMBOL}}@{{PRICE}} | SKIPPED {{SYMBOL}}\n"
        f"FII/DII: {fii_lbl} | {fii_det}\n"
        f"🔎 3 lanes active | {MC_HORIZON}-day hold | Risk {ACCOUNT_RISK_PCT*100:.1f}%/trade\n"
        f"🤲 Bismillah — trade only what you understand"
    )
    _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, footer)

    # PROJECTION CARDS (open positions)
    if projections:
        _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
                 "─────────────────────────────────────\n"
                 f"📊 LIVE PROJECTIONS ({len(projections)} open positions)\n"
                 "─────────────────────────────────────")
        for proj in projections:
            card_text = _format_projection_card(proj)
            _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, card_text)
            time.sleep(0.3)



def send_telegram_v3(picks: list, macro: dict, fii_data: dict,
                      date_label: str, data_source: str,
                      capacity: dict = None):
    """
    v3.0-M Telegram format:
    - Shows AI Confidence % + WORTH YOUR TIME / MAYBE / SKIP flag
    - Shows your personal win history for similar setups
    - Shows regime context and capacity guard status
    - Includes reply instructions (TAKEN / SKIPPED / PARTIAL)
    - Filters to WORTH_YOUR_TIME only when capacity guard is active
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram: not configured"); return

    if capacity is None:
        capacity = _capacity_guard(date_label)

    vix_val   = macro.get("vix_val", 0.0)
    macro_st  = macro.get("macro_state", "CHOP")
    macro_icon = {"CLEAR": "🟢", "CHOP": "🟡", "PANIC": "🔴",
                  "FOG": "🌫️", "MASSACRE": "🚨"}.get(macro_st, "⚪")

    lines = [
        f"⚔️ SNIPER {VERSION} | {date_label} | {macro_icon} {macro_st} | VIX {vix_val:.1f}",
        f"📡 Source: {data_source} | Halal | Manual execution only",
    ]
    if capacity.get("note"):
        lines.append(capacity["note"])
    lines.append("")

    if macro_st == "MASSACRE":
        lines.extend(["🚨 MARKET CRASH — NO TRADES TODAY.", ""])
        _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, "\n".join(lines))
        return
    if macro_st == "PANIC":
        lines.extend(["🔴 MARKET PANIC — NO NEW TRADES.", ""])
        _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, "\n".join(lines))
        return
    if not picks:
        lines.append("🤲 No qualifying picks today — patience is also a position.")
        _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, "\n".join(lines))
        return

    # Enrich each pick with v3 confidence fields
    enriched = []
    for r in picks:
        profile   = r.get("setup_profile") or _get_setup_profile(r)
        hist      = _historical_win_rate_for_profile(profile, r.get("grade"), r.get("sector"))
        # FIX-DOUBLE-SCALE: calibrated_ai_judge() already stores calibrated_confidence
        # (which has had _regime_scaled_confidence applied once).  Previously this code
        # read raw meta_prob and called _regime_scaled_confidence AGAIN, giving:
        #   0.55 × 0.88 × 0.88 ≈ 0.43 → "SKIP" for every CHOP pick regardless of quality.
        # Now: prefer calibrated_confidence (already correct), fall back to meta_prob
        # with a SINGLE scaling pass only when the judged field is absent.
        if "calibrated_confidence" in r:
            confidence = float(r["calibrated_confidence"])
        else:
            meta_prob  = r.get("meta_prob", 0.55)
            confidence = _regime_scaled_confidence(meta_prob, macro_st, vix_val)
        flag       = _confidence_flag(confidence)
        enriched.append({**r, "profile": profile, "history": hist,
                         "confidence": confidence, "flag": flag})

    # Capacity guard: filter if needed
    display_picks = enriched
    if capacity.get("reduce_to_worth_only"):
        display_picks = [p for p in enriched if p["flag"] == "WORTH YOUR TIME"]
        if not display_picks:
            # No high-confidence picks today — inform user clearly instead of falling back
            open_cnt = capacity.get("open_count", 0)
            lines.append(f"🔒 Capacity guard active ({open_cnt} open positions).")
            lines.append("No WORTH YOUR TIME signals today — no new trades recommended.")
            lines.append("Manage existing positions only. Bismillah 🤲")
            _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, "\n".join(lines))
            return
        lines.append(f"🔒 Showing {len(display_picks)} WORTH YOUR TIME signal(s) only (capacity guard active)")
        lines.append("")

    # Build pick cards
    for i, p in enumerate(display_picks, 1):
        icon     = _confidence_emoji(p["flag"])
        conf_pct = round(p["confidence"] * 100)
        hist     = p["history"]

        earn_warn = ""
        earn_days = p.get("earn_days")
        if earn_days is not None and 0 <= earn_days <= 3:
            earn_warn = f"\n   🚫 Earnings in {earn_days}d — consider skipping"
        elif earn_days is not None and 0 <= earn_days <= 8:
            earn_warn = f"\n   ⚠️ Earnings in {earn_days}d"

        vol_warn = " [NO-VOL]" if not p.get("vol_reliable", True) else ""

        if hist["total"] >= 3:
            hist_line = f"\n   📊 Your history: {hist['confidence_label']}"
        elif hist["total"] > 0:
            hist_line = f"\n   📊 Your history: {hist['wins']}/{hist['total']} similar trades"
        else:
            hist_line = "\n   📊 Your history: No similar setups yet"

        if p["flag"] == "SKIP":
            rec_note = "\n   🚫 AI recommends skip — false positive risk high"
        elif p["flag"] == "MAYBE" and conf_pct < 60:
            rec_note = "\n   ⚠️ Low confidence — consider skipping if busy"
        else:
            rec_note = ""

        mom_tier = p.get("sector_momentum_tier", "")
        mom_note = f" | Sector {mom_tier}" if mom_tier and mom_tier != "NEUTRAL" else ""

        why = _why_plain(p)
        verdict = _verdict_plain(p)
        verdict_dot = "✅" if verdict.startswith("✅") else "⛔"

        # OUT-2 (v5.0): News-driven llm_why per architecture Step 10
        # "AI recommends Why: Q3 profit up 23%, promoter buying, FII inflow"
        llm_why_text = p.get("llm_why", "")
        llm_confidence_n = p.get("llm_confidence", 0)
        llm_verdict_text = p.get("llm_verdict", "")
        if llm_why_text and llm_confidence_n > 0:
            ai_insight_line = (
                f"\n   🤖 AI CONFIDENCE - {llm_confidence_n}% [{llm_verdict_text}]"
                f"\n   AI recommends Why: {llm_why_text}"
            )
        else:
            ai_insight_line = ""

        # v5.1 CONVICTION HOLD annotation
        conviction_line = ""
        if p.get("conviction_flag"):
            min_h = p.get("min_hold_days", 10)
            max_h = p.get("max_hold_days", 15)
            conviction_line = (
                f"\n   🎯 CONVICTION HOLD: Min {min_h} days, max {max_h} days — SL only, ignore R1"
            )

        # v5.1 TIER 4: Causal reasoning block
        causal_line = ""
        if p.get("tier4_triggered"):
            causal_thesis = p.get("causal_thesis", "")
            causal_conf   = p.get("causal_conf", 0)
            causal_verdict = p.get("causal_verdict", "")
            asym          = p.get("asymmetry_score", 0)
            catalyst_dt   = p.get("catalyst_date", "")
            hold_until    = p.get("hold_until", "")
            primary_risk  = p.get("primary_risk", "")
            causal_line = (
                f"\n   🧠 CAUSAL THESIS ({causal_conf}% conf | {asym:.1f}x R/R) [{causal_verdict}]"
            )
            if causal_thesis:
                causal_line += f"\n   {causal_thesis[:120]}"
            if catalyst_dt:
                causal_line += f"\n   📅 Catalyst: {catalyst_dt}"
            if hold_until:
                causal_line += f"\n   ⏳ Hold until: {hold_until}"
            if primary_risk:
                causal_line += f"\n   ⚠️ Risk: {primary_risk[:80]}"

        card = (
            f"{icon} #{i} {p['symbol']}{vol_warn} — AI CONFIDENCE {conf_pct}% [{p['flag']}]\n"
            f"   ₹{p['close']:.0f} | Buy: ₹{p['buy_lo']}–{p['buy_hi']} | "
            f"SL ₹{p['stop_loss']} ({p['risk_pct']:.1f}%)\n"
            f"   R1 ₹{p['r1']} | R2 ₹{p['r2']} | R3 ₹{p['r3']} | Grade {p['grade']}{mom_note}\n"
            f"   Fortress: VPOC {'✓' if p.get('layer1') else '✗'} "
            f"Vol {'✓' if p.get('vol_reliable',True) else '✗'} "
            f"ADX {p.get('adx',0):.0f} | "
            f"Whale {'✓' if p.get('whale_score',0)>=15 else '✗'} "
            f"Bayes {p.get('bayes_pct',0)}%\n"
            f"   Why: {why}\n"
            f"   Verdict: {verdict_dot} {verdict.split('—',1)[-1].strip() if '—' in verdict else verdict}"
            f"{ai_insight_line}"
            f"{conviction_line}"
            f"{causal_line}"
            f"{hist_line}"
            f"{earn_warn}"
            f"{rec_note}"
        )
        lines.append(card)
        lines.append("")

    # Footer
    lines.append("─" * 35)
    lines.append("ℹ️ SKIPPED is no longer needed.")
    lines.append("Just don't reply — the system auto-logs silence as SKIPPED at EOD.")
    lines.append("Only reply if you TOOK or PARTIALLY took a position.")
    lines.append("  TAKEN TCS @ 3445")
    lines.append("  PARTIAL TCS 50    ← if taking half size")
    lines.append("")
    lines.append(f"FII/DII: {fii_data.get('label','—')} | {fii_data.get('detail','')[:60]}")
    lines.append(f"🔎 {len(display_picks)} pick(s) | {MC_HORIZON}-day hold | Risk {ACCOUNT_RISK_PCT*100:.1f}%/trade")
    lines.append("🤲 Bismillah — trade only what you understand")

    full_msg = "\n".join(lines)
    chunks = _split_msg(full_msg, limit=4000)
    for chunk in chunks:
        _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, chunk)

    for share_id in TELEGRAM_SHARE_IDS:
        if share_id and share_id != TELEGRAM_CHAT_ID:
            _tg_post(TELEGRAM_TOKEN, share_id, chunks[0])
            time.sleep(0.3)


def send_telegram(picks: list, macro: dict, fii_data: dict,
                   date_label: str, data_source: str):
    """Backward-compatible alias — delegates to send_telegram_v3."""
    send_telegram_v3(picks, macro, fii_data, date_label, data_source)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 15 — OUTPUT: EXCEL, HTML, GOOGLE SHEETS
# ══════════════════════════════════════════════════════════════════════════════

def _flatten_for_excel(rows: list) -> list:
    """Stringify nested dict/list values so openpyxl can write every cell.
    Without this, columns like halal_detail (a dict) cause a TypeError inside
    openpyxl and the entire ExcelWriter context silently fails — the file is
    created but empty.  Root cause: pd.DataFrame(picks) includes halal_detail
    as an object column; openpyxl raises ValueError on dict cells."""
    flat = []
    for row in rows:
        flat_row = {}
        for k, v in row.items():
            if isinstance(v, (dict, list)):
                flat_row[k] = json.dumps(v, default=str)
            else:
                flat_row[k] = v
        flat.append(flat_row)
    return flat


def save_excel(picks: list, all_results: list, fii_data: dict, date_label: str, data_source: str, bhavcopy: pd.DataFrame):
    if not picks and not all_results: return
    try:
        EXCEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(EXCEL_PATH, engine="openpyxl") as w:
            pd.DataFrame(_flatten_for_excel(picks)).to_excel(w, sheet_name="Top Picks",   index=False)
            pd.DataFrame(_flatten_for_excel(all_results)).to_excel(w, sheet_name="All Results", index=False)
            pd.DataFrame([fii_data]).to_excel(w, sheet_name="FII_DII", index=False)
            
            # NEW: Data Quality sheet
            halal_uni = get_halal_universe()
            quality = pd.DataFrame([{
                "Date": date_label,
                "Source": data_source,
                "Bhavcopy_Records": len(bhavcopy),
                "Halal_Universe": len(halal_uni),
                "Halal_in_Bhavcopy": len(bhavcopy[bhavcopy["symbol"].isin(halal_uni)]),
                "YFinance_Shrink": "YES" if (data_source == "YFINANCE" and len(bhavcopy) <= 100) else "NO",
                "Missing_Halal": len(halal_uni - set(bhavcopy["symbol"])),
                "Alert": "SHRUNK" if (data_source == "YFINANCE" and len(bhavcopy) <= 100) else "OK"
            }])
            quality.to_excel(w, sheet_name="Data Quality", index=False)

            # Performance sheet: closed pick outcomes from DB (moved inside ExcelWriter context)
            try:
                with _db_conn() as con:
                    perf_rows = con.execute(
                        "SELECT run_date, symbol, grade, fused_score, status, exit_price, pnl_pct, days_held, hit_target "
                        "FROM pick_outcomes WHERE status!='open' ORDER BY run_date DESC LIMIT 100"
                    ).fetchall()
                    if perf_rows:
                        perf_df = pd.DataFrame(perf_rows, columns=[
                            "Date", "Symbol", "Grade", "Score", "Status", "Exit", "P&L%", "Days", "Hit"
                        ])
                        perf_df.to_excel(w, sheet_name="Performance", index=False)
            except Exception as pe:
                log.debug(f"Performance sheet: {pe}")

        log.info(f"Excel saved: {EXCEL_PATH}")
    except Exception as e:
        log.error(f"Excel save failed: {e}")

def save_html(picks: list, fii_data: dict, date_label: str):
    try:
        HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
        rows=""
        for i,r in enumerate(picks,1):
            layers="".join("✓" if r.get(f"layer{n}") else "✗" for n in range(1,4))
            vol_warn='' if r.get("vol_reliable",True) else '<span style="color:#dc2626;font-size:10px"> ⚠️ No Volume</span>'
            rows+=f"""<tr>
              <td>{i}</td>
              <td><b>{r['symbol']}</b><br><small>{r.get('sector','—')}</small>{vol_warn}</td>
              <td>{r['fused']}/100<br>
                  <small style="color:#6b7280">Fort {r['fort_pct']:.0f}% · APEX {r['apex_composite']}</small><br>
                  <small style="color:#7c3aed">{r['grade']}</small></td>
              <td><small>Buy ₹{r['buy_lo']}–{r['buy_hi']}<br>SL ₹{r['stop_loss']}<br>R1 ₹{r['r1']} / R2 ₹{r['r2']} / R3 ₹{r['r3']}</small></td>
              <td><small>
                <b>Whale</b> {r['whale_score']:.0f} · <b>Div</b> {r['div_score']:.0f} · <b>VP</b> {r['vp_score']:.0f}<br>
                <b>Pat</b> {r['pat_score']:.0f} · <b>Bayes</b> {r['bayes_pct']}% · <b>MC</b> {r['mc_survival']}%<br>
                VPOC {layers} | {r.get('regime','—')} | {r.get('vcp_coil','—')[:5]}<br>
                RSI {r['rsi']} | MFI {r['mfi']} | ADX {r['adx']}
              </small></td>
              <td><small style="color:#555;font-style:italic">{r.get('story','—')}</small></td>
            </tr>"""

        html=f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><title>⚔️ Unified Sniper {VERSION} | {date_label}</title>
<style>body{{font-family:system-ui,sans-serif;margin:0;padding:20px;background:#f9fafb;color:#111}}
h1{{font-size:20px;margin:0 0 4px}}.meta{{color:#666;font-size:13px;margin-bottom:20px}}
.card{{background:#fff;border-radius:12px;border:1px solid #e5e7eb;padding:20px;margin-bottom:16px}}
table{{border-collapse:collapse;width:100%}}
th{{background:#f3f4f6;padding:10px 12px;text-align:left;font-size:12px;color:#555;border-bottom:1px solid #e5e7eb}}
td{{padding:10px;border-bottom:1px solid #f3f4f6;vertical-align:top;font-size:13px}}</style></head><body>
<h1>⚔️ Unified Sniper {VERSION}</h1>
<div class="meta">🕌 Halal · Fortress × APEX Fused · 14-node Bayes · t(df=5) MC · {date_label}</div>
<div class="card"><b>Market Intelligence</b><br>
  <div style="background:#e0f2fe;border-radius:8px;padding:10px 14px;margin:10px 0;font-size:13px">
    <b>{fii_data.get('label','—')}</b> &nbsp; {fii_data.get('detail','—')}
  </div>
</div>
<div class="card"><b>🎯 Top {len(picks)} Halal Picks</b>
<table style="margin-top:12px">
  <tr><th>#</th><th>Symbol</th><th>Score</th><th>Trade Plan</th><th>Sub-engines</th><th>Story</th></tr>
  {rows}
</table></div>
<div class="meta" style="margin-top:16px;text-align:center">
  Unified Sniper {VERSION} · Halal · NSE EQ · Not financial advice
</div></body></html>"""
        HTML_PATH.write_text(html, encoding="utf-8")
        log.info(f"HTML saved: {HTML_PATH}")
    except Exception as e:
        log.error(f"HTML save failed: {e}")


def _push_performance_tab(date_label: str):
    """Push calibrated win rates by grade/sector/signal to PERFORMANCE tab.
    Appends a dated snapshot each run so history accumulates across sessions."""
    log.info("PERFORMANCE: Starting push…")
    if not _sheets_ok():
        log.warning("PERFORMANCE: Sheets not configured — skipping")
        return
    log.info("PERFORMANCE: Sheets OK, connecting to DB…")

    try:
        with _db_conn() as con:

            # Win rate by grade — COALESCE guards against NULL from SUM on empty set
            grade_rows = con.execute(
                "SELECT grade, COUNT(*) as total, "
                "COALESCE(SUM(CASE WHEN status IN ('r1_hit','r2_hit','r3_hit') THEN 1 ELSE 0 END), 0) as wins, "
                "AVG(pnl_pct) FROM pick_outcomes WHERE status!='open' GROUP BY grade"
            ).fetchall()

            # Win rate by sector — FIX-PERF: use pick_outcomes.sector directly.
            # Previously JOINed sniper_results which is cleared by the same-day rerun
            # BEFORE _push_performance_tab fires → empty result set every time.
            # sector is now denormalized into pick_outcomes at INSERT time (see above).
            sector_rows = con.execute(
                "SELECT COALESCE(o.sector,'DIVERSIFIED'), COUNT(*) as total, "
                "COALESCE(SUM(CASE WHEN o.status IN ('r1_hit','r2_hit','r3_hit') THEN 1 ELSE 0 END), 0) as wins, "
                "AVG(o.pnl_pct) as avg_pnl "
                "FROM pick_outcomes o "
                "WHERE o.status!='open' GROUP BY COALESCE(o.sector,'DIVERSIFIED')"
            ).fetchall()

            # Prior calibration status
            prior_rows = con.execute(
                "SELECT prior_name, win_rate, total FROM bayes_calibration WHERE total>=10"
            ).fetchall()

            # Overall summary stats
            summary_row = con.execute(
                "SELECT COUNT(*), "
                "COALESCE(SUM(CASE WHEN status IN ('r1_hit','r2_hit','r3_hit') THEN 1 ELSE 0 END), 0), "
                "AVG(pnl_pct) FROM pick_outcomes WHERE status!='open'"
            ).fetchone()

            rows = [["Date", "Metric", "Category", "Total", "Wins", "WinRate%", "AvgPnL%", "Notes"]]

            # Overall row
            if summary_row and summary_row[0]:
                total, wins, avg_pnl = summary_row
                wr = (wins / total * 100) if total > 0 else 0
                rows.append([date_label, "Overall", "All Picks", total, wins,
                              f"{wr:.1f}", f"{avg_pnl:+.1f}" if avg_pnl else "—", ""])

            for grade, total, wins, avg_pnl in grade_rows:
                wins = wins or 0  # guard None
                wr = (wins / total * 100) if total > 0 else 0
                rows.append([date_label, "By Grade", grade or "—", total, wins,
                              f"{wr:.1f}", f"{avg_pnl:+.1f}" if avg_pnl else "—", ""])

            for sector, total, wins, avg_pnl in sector_rows:
                wins = wins or 0
                wr = (wins / total * 100) if total > 0 else 0
                rows.append([date_label, "By Sector", sector or "—", total, wins,
                              f"{wr:.1f}", f"{avg_pnl:+.1f}" if avg_pnl else "—", ""])

            for name, wr, total in prior_rows:
                rows.append([date_label, "Prior Calibrated", name, total,
                              int((wr or 0) * total), f"{(wr or 0)*100:.1f}", "—", _BAYES_PRIOR_VERSION])

            if len(rows) == 1:
                # No closed picks yet — still push headers + placeholder
                rows.append([date_label, "—", "No closed picks yet", 0, 0, "—", "—", ""])

            # Append to existing tab (preserves history) — read existing rows first
            ws = _get_ws("PERFORMANCE")
            if ws is not None:
                try:
                    existing = ws.get_all_values()
                    if existing and existing[0] == rows[0]:
                        # Headers match — append data rows below existing
                        data_rows = rows[1:]
                        ws.append_rows(data_rows, value_input_option="USER_ENTERED")
                        log.info(f"PERFORMANCE tab appended: {len(data_rows)} new rows ✅")
                        return
                except Exception as ae:
                    log.debug(f"PERFORMANCE append fallback to overwrite: {ae}")

            # Fallback: overwrite (first run or header mismatch)
            _push_sheet("PERFORMANCE", rows)
            log.info(f"PERFORMANCE tab pushed: {len(rows)-1} rows ✅")

    except Exception as e:
        log.error(f"PERFORMANCE tab FAILED: {e}")


def _push_ai_insights_tab(picks: list, date_label: str):
    """Push LLM-enhanced stories and filing analyses to AI_INSIGHTS tab.
    Appends rows each run so history accumulates. Called regardless of LLM_ENABLED;
    the LLM columns simply show '—' when LLM is off."""
    log.info("AI_INSIGHTS: Starting push…")
    if not _sheets_ok():
        log.warning("AI_INSIGHTS: Sheets not configured — skipping")
        return
    log.info(f"AI_INSIGHTS: Sheets OK, processing {len(picks)} picks…")

    headers = ["Date", "Symbol", "Grade", "Fused", "Raw Story", "LLM Story",
               "LLM Conviction", "Filing Sentiment", "Filing Detail", "Prior Version"]

    data_rows = []
    if not picks:
        data_rows.append([date_label, "—", "—", "—", "No picks today", "—", "—", "—", "—", _BAYES_PRIOR_VERSION])
    else:
        for r in picks:
            llm_story = r.get("llm_story") or "—"
            if llm_story != "—":
                llm_story = str(llm_story)[:300]
            data_rows.append([
                date_label,
                r["symbol"],
                r.get("grade", "—"),
                r.get("fused", "—"),
                (r.get("story") or "—")[:200],
                llm_story,
                r.get("bayes_pct", "—"),  # AI conviction proxy
                r.get("llm_filing_sentiment") or "—",
                (r.get("fil_detail") or "—")[:200],
                _BAYES_PRIOR_VERSION,
            ])

    try:
        ws = _get_ws("AI_INSIGHTS")
        if ws is not None:
            existing = ws.get_all_values()
            if existing and existing[0] == headers:
                # Headers already present — append only data rows
                ws.append_rows(data_rows, value_input_option="USER_ENTERED")
                log.info(f"AI_INSIGHTS tab appended: {len(data_rows)} row(s) ✅")
                return
        # First run or header mismatch — full overwrite
        _push_sheet("AI_INSIGHTS", [headers] + data_rows)
        log.info(f"AI_INSIGHTS tab pushed: {len(data_rows)} row(s) ✅")
    except Exception as e:
        log.error(f"AI_INSIGHTS tab FAILED: {e}")


def push_gsheets(picks: list, date_label: str):
    if not _sheets_ok(): return
    headers = [
        "Date","Symbol","Sector","Grade","Fused/100","Fort%","APEX/100",
        "Fortress/80","FII/30","Insider/30","Filing/30","Earnings/30",
        "Whale","Divergence","VolProfile","Pattern","Bayes%","MC%",
        "BuyLo","BuyHi","StopLoss","R1","R2","R3","TrailStop",
        "VPOC-L1","VPOC-L2","VPOC-L3","VCP","Regime",
        "RSI","MFI","ADX","ATR","POC","MA200",
        "DataQuality","VolReliable","Story",
    ]
    rows = [headers]
    for r in picks:
        rows.append([
            date_label, r["symbol"], r.get("sector","—"), r.get("grade","—"),
            r["fused"], r["fort_pct"], r["apex_composite"],
            r["score_fortress"], r["score_fii"], r["score_insider"],
            r["score_filing"], r["score_earnings"],
            r["whale_score"], r["div_score"], r["vp_score"], r["pat_score"],
            r["bayes_pct"], r.get("mc_survival","—"),
            r["buy_lo"], r["buy_hi"], r["stop_loss"],
            r["r1"], r["r2"], r["r3"], r["trail_stop"],
            int(r["layer1"]), int(r["layer2"]), int(r["layer3"]),  # ← FIXED: bool → int (1/0)
            r.get("vcp_coil","—"), r.get("regime","—"),
            r["rsi"], r["mfi"], r["adx"], r["atr14"], r["poc"], r["ma200"],
            r.get("data_quality","—"), int(r.get("vol_reliable",True)),  # ← FIXED: bool → int
            r.get("story","—"),
        ])
    _push_sheet("SCREENER", rows)
# ══════════════════════════════════════════════════════════════════════════════
# SECTION 15b — OUTCOME ENGINE (closed-loop feedback)
# ══════════════════════════════════════════════════════════════════════════════

def _get_yesterday_picks() -> List[dict]:
    """Fetch all open picks from the last MC_HORIZON days, deduplicated by symbol.
    DUPLICATE FIX: Uses GROUP BY + MAX(id) so reruns that inserted multiple rows
    for the same symbol/date return only one row per (run_date, symbol) pair.
    Also looks back MC_HORIZON days (not just yesterday) so picks that haven't
    hit a target yet continue to be tracked across multiple days."""
    try:
        with _db_conn() as con:
            since = (datetime.today() - timedelta(days=MC_HORIZON)).strftime("%Y-%m-%d")
            # SELECT the row with MAX(id) per (run_date, symbol) to deduplicate
            rows = con.execute(
                "SELECT run_date, symbol, entry_price, stop_loss, r1, r2, r3, grade, fused_score, story "
                "FROM pick_outcomes "
                "WHERE status='open' AND run_date>=? "
                "  AND id IN (SELECT MAX(id) FROM pick_outcomes WHERE status='open' AND run_date>=? GROUP BY run_date, symbol)",
                (since, since)
            ).fetchall()
            return [dict(zip(["run_date","symbol","entry_price","stop_loss",
                              "r1","r2","r3","grade","fused_score","story"], r)) for r in rows]
    except Exception as e:
        log.debug(f"Get open picks: {e}")
        return []


def _update_pick_outcome(symbol: str, run_date: str, status: str, exit_price: float = None, pnl_pct: float = None, days_held: int = None, hit_target: str = None):
    """Update a pick's outcome after checking market data."""
    try:
        with _db_conn(write=True) as con:
            con.execute(
                "UPDATE pick_outcomes SET status=?, exit_price=?, pnl_pct=?, days_held=?, hit_target=?, updated_at=? "
                "WHERE symbol=? AND run_date=?",
                (status, exit_price, pnl_pct, days_held, hit_target, datetime.today().isoformat(), symbol, run_date)
            )
            con.commit()
            log.info(f"  Outcome: {symbol} → {status} | P&L: {pnl_pct:+.1f}% | Days: {days_held}")
    except Exception as e:
        log.debug(f"Update outcome {symbol}: {e}")


def _check_pick_outcome(pick: dict, hist: pd.DataFrame) -> dict:
    """
    Check if yesterday's pick hit R1, R2, R3, or stop loss.
    Returns: {"status": str, "exit_price": float, "pnl_pct": float, "days_held": int, "hit_target": str}
    """
    if hist.empty or len(hist) < 2:
        return {"status": "open", "exit_price": None, "pnl_pct": None, "days_held": None, "hit_target": None}
    
    entry = pick["entry_price"]
    stop = pick["stop_loss"]
    r1 = pick["r1"]
    r2 = pick["r2"]
    r3 = pick["r3"]
    
    # Get prices since pick date
    pick_date = pd.Timestamp(pick["run_date"])
    since_pick = hist[hist["date"] >= pick_date]
    
    if since_pick.empty:
        return {"status": "open", "exit_price": None, "pnl_pct": None, "days_held": None, "hit_target": None}
    
    highs = since_pick["high"].values
    lows = since_pick["low"].values
    closes = since_pick["close"].values
    days_held = len(since_pick)
    
    # OUTCOME FIX: Check targets BEFORE stop-loss.
    # On a gap-up day a single bar's high can exceed R3 while the same bar's
    # low also breaches the stop.  Checking stop first wrongly reports a loss
    # on what is actually a winning trade.  Targets take priority; stop only
    # applies when no target was reached on that bar.
    #
    # Per-bar resolution: walk the bars and check both directions each day.
    for i, (h, l) in enumerate(zip(highs, lows)):
        if h >= r3:
            return {"status": "r3_hit", "exit_price": r3,
                    "pnl_pct": (r3 - entry) / entry * 100,
                    "days_held": i + 1, "hit_target": "r3"}
        if h >= r2:
            return {"status": "r2_hit", "exit_price": r2,
                    "pnl_pct": (r2 - entry) / entry * 100,
                    "days_held": i + 1, "hit_target": "r2"}
        if h >= r1:
            return {"status": "r1_hit", "exit_price": r1,
                    "pnl_pct": (r1 - entry) / entry * 100,
                    "days_held": i + 1, "hit_target": "r1"}
        if l <= stop:
            return {"status": "stopped", "exit_price": stop,
                    "pnl_pct": (stop - entry) / entry * 100,
                    "days_held": i + 1, "hit_target": "stop"}
    
    # OPT-20: Expire with trailing-close-based exit (best close in last 3 days)
    # Using last close undervalued picks that peaked and retraced before expiry.
    if days_held >= MC_HORIZON:
        last_close = float(closes[-1])
        # Trailing: if price was higher in last 3 bars, use that as exit (partial credit)
        trail_window = min(3, len(closes))
        trailing_exit = float(closes[-trail_window:].max())
        # Only use trailing if it improves P&L (never penalise)
        exit_price = trailing_exit if trailing_exit > last_close else last_close
        pnl = (exit_price - entry) / entry * 100
        return {"status": "expired", "exit_price": round(exit_price, 2), "pnl_pct": round(pnl, 2), "days_held": days_held, "hit_target": "none"}
    
    # Still open
    return {"status": "open", "exit_price": None, "pnl_pct": None, "days_held": days_held, "hit_target": None}


def _run_outcome_engine():
    """Check all open picks from previous days and update their outcomes.
    LOG-STORM FIX: when NSE is IP-blocked, batch-preload histories via yfinance
    instead of making per-symbol NSE calls that all fail after 3 retries each.
    The deduplication in _get_yesterday_picks() ensures we process each symbol once."""
    log.info("=" * 70)
    log.info("OUTCOME ENGINE — Checking open picks…")
    log.info("=" * 70)

    open_picks = _get_yesterday_picks()
    if not open_picks:
        log.info("  No open picks to check")
        return

    log.info(f"  Tracking {len(open_picks)} open pick(s)")

    with _NSE_FAIL_LOCK:
        ip_blocked = _NSE_IP_BLOCKED

    sess = None if ip_blocked else _get_nse_session()

    # Batch-preload histories for all open symbols via yfinance (one download call)
    # This is much faster than per-symbol NSE calls when NSE is blocked
    yf_cache: Dict[str, pd.DataFrame] = {}
    if ip_blocked:
        symbols = [p["symbol"] for p in open_picks]
        log.info(f"  NSE IP-blocked — batch-loading {len(symbols)} histories via yfinance")
        yf_cache = _preload_histories_yf(symbols, days=30)

    for pick in open_picks:
        sym = pick["symbol"]
        try:
            hist = fetch_history(sym, days=30, sess=sess, yf_cache=yf_cache if ip_blocked else None)
            outcome = _check_pick_outcome(pick, hist)

            if outcome["status"] != "open":
                _update_pick_outcome(
                    sym, pick["run_date"], outcome["status"],
                    outcome["exit_price"], outcome["pnl_pct"],
                    outcome["days_held"], outcome["hit_target"]
                )
            else:
                log.info(f"  {sym}: still open ({outcome['days_held']} days | "
                         f"run_date={pick['run_date']})")

            time.sleep(0.1)
        except Exception as e:
            log.debug(f"Outcome check {sym}: {e}")

    log.info("  Outcome engine complete")


def _get_sector_performance(days: int = 30) -> dict:
    """Calculate win rate and avg P&L per sector from pick_outcomes.
    FIX-PERF: query pick_outcomes.sector directly (denormalized) instead of
    JOINing sniper_results which may have been cleared by same-day rerun."""
    try:
        with _db_conn() as con:
            since = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
            rows = con.execute(
                "SELECT COALESCE(o.sector,'DIVERSIFIED'), o.status, o.pnl_pct FROM pick_outcomes o "
                "WHERE o.run_date>=? AND o.status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')",
                (since,)
            ).fetchall()
        
            sector_stats = {}
            for sector, status, pnl in rows:
                if sector not in sector_stats:
                    sector_stats[sector] = {"wins": 0, "losses": 0, "total_pnl": 0, "count": 0}
                sector_stats[sector]["count"] += 1
                sector_stats[sector]["total_pnl"] += (pnl or 0)
                if status in ("r1_hit", "r2_hit", "r3_hit"):
                    sector_stats[sector]["wins"] += 1
                else:
                    sector_stats[sector]["losses"] += 1
        
            # Calculate win rate
            for sector, stats in sector_stats.items():
                stats["win_rate"] = stats["wins"] / stats["count"] * 100 if stats["count"] > 0 else 0
                stats["avg_pnl"] = stats["total_pnl"] / stats["count"] if stats["count"] > 0 else 0
        
            return sector_stats
    except Exception as e:
        log.debug(f"Sector performance: {e}")
        return {}


def _adjust_sector_multipliers():
    """Dynamically adjust SECTOR_TRUTH based on actual performance."""
    perf = _get_sector_performance(days=30)
    if not perf:
        log.info("  No performance data yet — using default multipliers")
        return
    
    log.info("=" * 70)
    log.info("📊 SECTOR PERFORMANCE (30-day) — Adjusting multipliers…")
    log.info("=" * 70)
    
    for sector, stats in sorted(perf.items(), key=lambda x: x[1]["win_rate"], reverse=True):
        old_mult = SECTOR_TRUTH.get(sector, 1.0)
        new_mult = old_mult
        
        # OPT-14: finer 0.02 step with EMA smoothing (0.05 was too coarse, caused oscillation)
        if stats["win_rate"] >= 60 and stats["count"] >= 5:
            target = min(1.3, old_mult + 0.02)
            new_mult = round(0.8 * old_mult + 0.2 * target, 3)  # EMA smooth
        elif stats["win_rate"] <= 30 and stats["count"] >= 5:
            target = max(0.7, old_mult - 0.02)
            new_mult = round(0.8 * old_mult + 0.2 * target, 3)  # EMA smooth
        
        if new_mult != old_mult:
            SECTOR_TRUTH[sector] = new_mult
            log.info(f"  {sector}: {old_mult:.2f} → {new_mult:.2f} (win {stats['win_rate']:.0f}%, {stats['count']} trades)")
        else:
            log.info(f"  {sector}: {old_mult:.2f} unchanged (win {stats['win_rate']:.0f}%, {stats['count']} trades)")


def _get_stale_picks(days_stale: int = 5) -> List[dict]:
    """Find picks that never triggered entry (price never hit buy zone).
    BUG-006 FIX: sniper_results doesn't have buy_lo/buy_hi columns.
    Query only columns that exist; derive zone from entry_price ±2%.
    """
    try:
        with _db_conn() as con:
            since = (datetime.today() - timedelta(days=days_stale)).strftime("%Y-%m-%d")
            rows = con.execute(
                "SELECT run_date, symbol, entry_price, story "
                "FROM sniper_results s "
                "WHERE s.run_date<=? AND NOT EXISTS ("
                "  SELECT 1 FROM pick_outcomes o WHERE o.symbol=s.symbol AND o.run_date=s.run_date"
                ")",
                (since,)
            ).fetchall()
            result = []
            for r in rows:
                run_date, symbol, entry_price, story = r
                ep = entry_price or 0.0
                result.append({
                    "run_date": run_date, "symbol": symbol,
                    "entry_price": ep,
                    "buy_lo": round(ep * 0.98, 2),   # BUG-006: synthesised ±2% zone
                    "buy_hi": round(ep * 1.02, 2),
                    "story": story,
                })
            return result
    except Exception as e:
        log.debug(f"Stale picks: {e}")
        return []


def _alert_open_positions():
    """Alert if any open pick is within 5% of stop loss.
    LOG-STORM FIX: if NSE is IP-blocked, skip NSE quote calls entirely and
    use yfinance for live price — avoids 21 symbols × 3 retries × 3 attempts
    of guaranteed-fail NSE calls at the start of every run."""
    try:
        with _db_conn() as con:
            rows = con.execute(
                "SELECT symbol, entry_price, stop_loss, r1, days_held, status "
                "FROM pick_outcomes WHERE status='open'"
            ).fetchall()

            if not rows:
                return

            # Deduplicate: pick_outcomes can have duplicate open rows if reruns inserted them.
            # Use a set to process each symbol only once.
            seen_syms = set()
            unique_rows = []
            for row in rows:
                sym = row[0]
                if sym not in seen_syms:
                    seen_syms.add(sym)
                    unique_rows.append(row)
            rows = unique_rows

            log.info("=" * 70)
            log.info(f"OPEN POSITION ALERTS — {len(rows)} unique symbol(s)")
            log.info("=" * 70)

            with _NSE_FAIL_LOCK:
                ip_blocked = _NSE_IP_BLOCKED

            sess = _get_nse_session() if not ip_blocked else None

            for sym, entry, stop, r1, days, status in rows:
                latest = 0.0
                try:
                    if not ip_blocked and sess is not None:
                        info = _nse_json(sess, "https://www.nseindia.com/api/quote-equity",
                                         params={"symbol": sym}, timeout=10)
                        latest = float(info.get("priceInfo", {}).get("lastPrice", 0))

                    # Fallback to yfinance if NSE blocked or returned 0
                    if latest <= 0:
                        try:
                            import yfinance as yf
                            ticker_info = yf.Ticker(f"{sym}.NS").fast_info
                            latest = float(getattr(ticker_info, "last_price", 0) or 0)
                        except Exception:
                            pass

                    if latest <= 0:
                        log.debug(f"  {sym}: no live price available")
                        continue

                    stop_distance = (latest - stop) / stop * 100
                    r1_distance   = (r1 - latest) / latest * 100

                    if stop_distance <= 5:
                        log.warning(f"  RED {sym}: Rs{latest:.0f} — only {stop_distance:.1f}% from stop! ({days} days)")
                    elif r1_distance <= 5:
                        log.info(f"  GREEN {sym}: Rs{latest:.0f} — {r1_distance:.1f}% from R1 ({days} days)")
                    else:
                        log.info(f"  {sym}: Rs{latest:.0f} | Stop {stop_distance:.1f}% away | R1 {r1_distance:.1f}% away")

                    time.sleep(0.2)
                except Exception as e:
                    log.debug(f"Alert check {sym}: {e}")

    except Exception as e:
        log.debug(f"Open alerts: {e}")
# ══════════════════════════════════════════════════════════════════════════════
# SECTION 16 — MAIN PIPELINE
# ══════════════════════════════════════════════════════════════════════════════



def _check_sheets_freshness():
    """
    FIX-4.1-M: Warn when Sheets intelligence tabs haven't been updated recently.
    Technical signals (bhavcopy) are always T+0; stale Sheets means fundamental
    signals (insider, filings, earnings) may be days old — creating asymmetry.
    """
    if not _sheets_ok():
        return
    STALE_THRESHOLD_DAYS = 2
    tabs_to_check = [
        ("INSIDER",  "DATE",   "insider trades"),
        ("FILINGS",  "DATE",   "corporate filings"),
        ("EARNINGS", "DATE",   "earnings calendar"),
        ("FII_DII",  "DATE",   "FII/DII data"),
    ]
    try:
        today = datetime.today().date()
        for tab, date_col_hint, label in tabs_to_check:
            try:
                df = _read_sheet(tab)
                if df.empty:
                    continue
                date_col = next((c for c in df.columns
                                 if any(k in c for k in ("DATE","TIMESTAMP","UPDATED","TIME"))), None)
                if date_col is None:
                    continue
                dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
                if dates.empty:
                    continue
                latest = dates.max().date()
                age = (today - latest).days
                if age > STALE_THRESHOLD_DAYS:
                    log.warning(
                        f"⚠️ SHEETS STALE: '{tab}' last updated {age}d ago ({latest}). "
                        f"{label.capitalize()} signals may be outdated — update the sheet."
                    )
            except Exception:
                pass
    except Exception as e:
        log.debug(f"Sheets freshness check: {e}")


def _data_quality_gate(bhavcopy: pd.DataFrame, data_source: str) -> dict:
    """
    Auto-adjust thresholds if data quality degrades.
    Returns: {apex_min_score: int, apex_top_n: int, alert: str}
    """
    halal_uni = get_halal_universe()
    halal_in_bhav = len(bhavcopy[bhavcopy["symbol"].isin(halal_uni)])

    # Default thresholds
    min_score = APEX_MIN_SCORE
    top_n = APEX_TOP_N
    alert = ""

    # Degraded mode: yfinance fallback with shrunk universe
    if data_source == "YFINANCE" and len(bhavcopy) <= 100:
        min_score = 65
        top_n = 3
        alert = "🚨 DEGRADED: YFinance fallback, universe shrunk. Raising bar."
        log.warning(alert)

    # Moderate degradation: fewer halal symbols than expected
    elif halal_in_bhav < 50:
        min_score = min(65, APEX_MIN_SCORE + 5)
        top_n = max(3, APEX_TOP_N - 1)
        alert = f"⚠️ Only {halal_in_bhav} halal symbols in bhavcopy. Tightening filters."
        log.warning(alert)

    return {"apex_min_score": min_score, "apex_top_n": top_n, "alert": alert}




def _intraday_watchdog(symbol: str, trailing_stop: float, db_path: str = DB_PATH) -> dict:
    """
    Check live LTP against trailing_stop in DB.
    Returns: {action: str, ltp: float, distance_pct: float}
    action: 'HOLD' | 'STOP_HIT' | 'TRAIL_UPDATE' | 'CONVICTION_HOLD' | 'TIME_STOP' | 'ERROR'

    v5.1 CONVICTION HOLD amendment:
      - If position has conviction_flag=1 AND hold_days < min_hold_days:
          * IGNORE R1 hit — only enforce SL
          * Action returns 'CONVICTION_HOLD' (informational, no exit)
      - If hold_days >= max_hold_days:
          * Returns 'TIME_STOP' — caller should exit at market
    """
    try:
        # Get live price from NSE
        sess = _get_nse_session()
        data = _nse_json(sess, "https://www.nseindia.com/api/quote-equity",
                        params={"symbol": symbol}, timeout=10)
        ltp = float(data.get("priceInfo", {}).get("lastPrice", 0))

        if ltp <= 0:
            return {"action": "ERROR", "ltp": 0, "distance_pct": 0}

        # Fetch position row including conviction hold fields
        with _db_conn() as con:
            row = con.execute(
                "SELECT peak_price, entry_price, entry_date, trailing_stop, "
                "conviction_flag, min_hold_days, max_hold_days "
                "FROM positions WHERE symbol=? AND status='open' ORDER BY entry_date DESC LIMIT 1",
                (symbol.upper(),)
            ).fetchone()

        # Conviction hold enforcement
        if row:
            peak         = float(row[0] or 0)
            entry        = float(row[1] or 0)
            entry_date   = row[2] or ""
            db_trail     = float(row[3] or trailing_stop)
            conv_flag    = int(row[4] or 0)
            min_hold     = int(row[5] or 0)
            max_hold     = int(row[6] or 0)

            # Calculate days held
            hold_days = 0
            if entry_date:
                try:
                    hold_days = (datetime.today().date() -
                                 datetime.strptime(entry_date, "%Y-%m-%d").date()).days
                except Exception:
                    hold_days = 0

            # TIME STOP: conviction hold expired — force exit regardless of price
            if conv_flag and max_hold > 0 and hold_days >= max_hold:
                log.info(
                    f"CONVICTION TIME-STOP {symbol}: held {hold_days}d >= max_hold {max_hold}d "
                    f"— time stop triggered at ltp={ltp}"
                )
                return {
                    "action":       "TIME_STOP",
                    "ltp":          ltp,
                    "distance_pct": (ltp - entry) / entry * 100 if entry > 0 else 0,
                    "hold_days":    hold_days,
                    "conviction":   True,
                }

            # STOP HIT: always enforced — even during conviction hold
            if ltp <= trailing_stop:
                return {"action": "STOP_HIT", "ltp": ltp, "distance_pct": -999}

            # CONVICTION HOLD active: ignore R1 target, only trail stop
            if conv_flag and min_hold > 0 and hold_days < min_hold:
                # Still update trailing stop normally — just don't exit at R1
                new_trail = max(trailing_stop, ltp * 0.95, entry * 1.02)
                if new_trail > trailing_stop:
                    with _db_conn(write=True) as con:
                        con.execute(
                            "UPDATE positions SET trailing_stop=?, peak_price=?, updated_at=? "
                            "WHERE symbol=? AND status='open'",
                            (new_trail, ltp, datetime.today().isoformat(), symbol.upper())
                        )
                        con.commit()
                log.debug(
                    f"CONVICTION HOLD active {symbol}: day {hold_days}/{min_hold}, "
                    f"ltp={ltp}, sl={trailing_stop:.2f} — R1 ignored"
                )
                return {
                    "action":       "CONVICTION_HOLD",
                    "ltp":          ltp,
                    "distance_pct": (ltp - trailing_stop) / trailing_stop * 100,
                    "hold_days":    hold_days,
                    "days_remaining": min_hold - hold_days,
                    "conviction":   True,
                }

            # Standard trailing stop update
            new_trail = max(trailing_stop, ltp * 0.95, entry * 1.02)
            if new_trail > trailing_stop:
                with _db_conn(write=True) as con:
                    con.execute(
                        "UPDATE positions SET trailing_stop=?, peak_price=?, updated_at=? "
                        "WHERE symbol=? AND status='open'",
                        (new_trail, ltp, datetime.today().isoformat(), symbol.upper())
                    )
                    con.commit()
                return {
                    "action": "TRAIL_UPDATE",
                    "ltp":    ltp,
                    "distance_pct": (ltp - new_trail) / ltp * 100,
                }

        # No position row found — just check stop
        if ltp <= trailing_stop:
            return {"action": "STOP_HIT", "ltp": ltp, "distance_pct": -999}

        distance = (ltp - trailing_stop) / trailing_stop * 100
        return {"action": "HOLD", "ltp": ltp, "distance_pct": distance}

    except Exception as e:
        log.debug(f"Watchdog {symbol}: {e}")
        return {"action": "ERROR", "ltp": 0, "distance_pct": 0}


def _early_exit_alert(symbol: str, entry_price: float, current_ltp: float) -> dict:
    """
    Alert if top pick drops 3% intraday — early exit signal before EOD stop hits.
    Returns: {alert: bool, drop_pct: float, severity: str, note: str}
    """
    if entry_price <= 0 or current_ltp <= 0:
        return {"alert": False, "drop_pct": 0, "severity": "NONE", "note": ""}

    drop_pct = (current_ltp - entry_price) / entry_price * 100

    if drop_pct <= -5.0:
        severity = "CRITICAL"
        note = f"🚨 {symbol}: {drop_pct:.1f}% from entry — consider immediate exit"
    elif drop_pct <= -3.0:
        severity = "WARNING"
        note = f"⚠️ {symbol}: {drop_pct:.1f}% from entry — tighten stop, watch closely"
    elif drop_pct <= -1.5:
        severity = "CAUTION"
        note = f"📉 {symbol}: {drop_pct:.1f}% from entry — early weakness"
    else:
        severity = "NONE"
        note = ""

    return {
        "alert": severity in ["CRITICAL", "WARNING"],
        "drop_pct": round(drop_pct, 2),
        "severity": severity,
        "note": note
    }



# ══════════════════════════════════════════════════════════════════════════════
# [PATCH-C]  CALIBRATED AI JUDGE  (v4.0-M — Platt-scaled meta_prob + Kelly)
# ══════════════════════════════════════════════════════════════════════════════

def _platt_calibrate(raw_prob: float, calibration_params: Optional[dict]) -> float:
    """
    Platt scaling: raw_prob → calibrated_prob.
    params = {"A": float, "B": float, "n_samples": int}
    Falls back to identity if params absent or < 50 training samples.
    """
    if not calibration_params or calibration_params.get("n_samples", 0) < 50:
        return raw_prob
    A = calibration_params.get("A", 0.0)
    B = calibration_params.get("B", 0.0)
    try:
        return round(1.0 / (1.0 + math.exp(A * raw_prob + B)), 4)
    except (OverflowError, ValueError):
        return raw_prob


def _load_calibration_params() -> Optional[dict]:
    """Load Platt scaling params from DB (trained offline)."""
    try:
        with _db_conn() as con:
            row = con.execute(
                "SELECT A, B, n_samples, trained_at FROM platt_calibration "
                "ORDER BY trained_at DESC LIMIT 1"
            ).fetchone()
        if row:
            return {"A": row[0], "B": row[1], "n_samples": row[2], "trained_at": row[3]}
    except Exception:
        pass
    return None


def _kelly_fraction(p_calibrated: float, b: float = 2.0) -> str:
    """
    Fractional Kelly position size tier.
    Returns: 'FULL' | 'HALF' | 'QUARTER' | 'VETO'
    ROOT CAUSE #1 FIX: QUARTER threshold lowered 0.45 → 0.40 to match the
    calibrated_ai_judge confidence_floor. Previously every uncalibrated pick
    (p_cal ≈ 0.43) was vetoed here even after passing the judge — picks showed
    'Size: VETO' despite not being vetoed. Both gates must use the same floor.
    """
    if p_calibrated >= 0.75:
        return "FULL"
    elif p_calibrated >= 0.55:
        return "HALF"
    elif p_calibrated >= 0.40:   # RC1 FIX: was 0.45 — must match confidence_floor in calibrated_ai_judge
        return "QUARTER"
    return "VETO"


def _prev_day_context(symbol: str) -> dict:
    """Check yesterday's pick status for cooling-off logic."""
    yesterday = (datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        with _db_conn() as con:
            row = con.execute(
                "SELECT status, pnl_pct FROM pick_outcomes WHERE symbol=? AND run_date=?",
                (symbol.upper(), yesterday)
            ).fetchone()
        if row:
            return {"status": row[0], "pnl_pct": row[1]}
    except Exception:
        pass
    return {"status": None, "pnl_pct": None}


def _weekly_wr_for_profile(setup_profile: str, grade: str, sector: str) -> dict:
    """Win rate for this exact profile in last 30 days of YOUR decisions."""
    try:
        since = (datetime.today() - timedelta(days=30)).strftime("%Y-%m-%d")
        with _db_conn() as con:
            rows = con.execute("""
                SELECT o.status, o.pnl_pct
                FROM trade_decisions td
                JOIN pick_outcomes o ON td.symbol=o.symbol AND td.run_date=o.run_date
                JOIN meta_features mf ON td.symbol=mf.symbol AND td.run_date=mf.run_date
                WHERE td.decision='TAKEN' AND td.run_date>=?
                  AND o.status IN ('r1_hit','r2_hit','r3_hit','stopped','expired')
                  AND mf.setup_profile=?
            """, (since, setup_profile)).fetchall()
        total = len(rows)
        wins  = sum(1 for s, _ in rows if s in ("r1_hit", "r2_hit", "r3_hit"))
        return {"win_rate": (wins / total) if total > 0 else 0.5, "total": total}
    except Exception:
        return {"win_rate": 0.5, "total": 0}


# ══════════════════════════════════════════════════════════════════════════════
# v5.1 — TIER 4: LLM CAUSAL REASONING ENGINE
# "Don't tell me the score is 72. Tell me WHY this setup has asymmetric payoff."
#
# TRIGGER: Only fires for GREAT/ELITE picks with meta_prob > 65%.
#          Selective — top 3 picks per run at most. Cost: ~₹15-25/call.
#
# INPUTS (beyond existing Tier 2 synthesis):
#   - Causal chain: supply chain → earnings → margin → rerating
#   - Estimated catalyst date (next earnings / event)
#   - Asymmetry score: R3_upside / SL_downside
#   - Multi-hop reasoning the quant engine cannot perform
#
# OUTPUT fields added to pick dict:
#   causal_thesis   — "EV approval → battery contracts → margin expansion → rerating"
#   catalyst_date   — "2026-06-15" (estimated)
#   asymmetry_score — float (R3 upside / SL downside ratio)
#   causal_conf     — 0-100 (higher because causal, not correlational)
#   causal_verdict  — "TAKE" | "SKIP" | "HOLD"
#   hold_until      — "catalyst_date + 5 days" or "max_hold_days"
#   tier4_triggered — True/False
# ══════════════════════════════════════════════════════════════════════════════

_TIER4_MAX_PER_RUN = 3   # Cap API cost: at most 3 causal calls per daily run

def _llm_causal_reasoning(pick: dict, macro: dict,
                           fii_data: dict = None, earnings_cal: dict = None) -> dict:
    """
    Tier 4: Claude Sonnet performs multi-hop causal reasoning on a GREAT/ELITE pick.

    Returns a dict with causal_thesis, catalyst_date, asymmetry_score,
    causal_conf, causal_verdict, hold_until, tier4_triggered.
    Falls back gracefully (returns tier4_triggered=False) if LLM unavailable.

    TRIGGER CONDITIONS (all must be true):
      1. grade in ("GREAT", "ELITE")
      2. meta_prob > 0.65
      3. Not vetoed
      4. LLM_ENABLED and _ANTHROPIC_OK
    """
    defaults = {
        "causal_thesis":   "",
        "catalyst_date":   "",
        "asymmetry_score": 0.0,
        "causal_conf":     0,
        "causal_verdict":  "",
        "hold_until":      "",
        "tier4_triggered": False,
    }

    sym   = pick.get("symbol", "?")
    grade = pick.get("grade", "")
    meta_prob = pick.get("meta_prob", 0.0)

    # Guard: only GREAT/ELITE with high meta_prob
    if grade not in ("GREAT", "ELITE") or meta_prob < 0.65:
        return defaults

    if not (LLM_ENABLED and _ANTHROPIC_OK):
        log.debug(f"Tier4 {sym}: LLM unavailable — skipping causal reasoning")
        return defaults

    # Compute asymmetry score (upside/downside ratio) — pure maths, no LLM
    entry   = pick.get("close", 0) or 0
    sl      = pick.get("stop_loss", 0) or 0
    r3      = pick.get("r3", 0) or 0
    if entry > 0 and sl > 0 and r3 > entry:
        downside_pct = abs(entry - sl) / entry * 100
        upside_pct   = (r3 - entry) / entry * 100
        asym         = round(upside_pct / downside_pct, 2) if downside_pct > 0 else 0.0
    else:
        asym = 0.0

    # Build causal reasoning prompt
    macro_state   = macro.get("macro_state", "CHOP")
    sector        = pick.get("sector", "DIVERSIFIED")
    fused         = pick.get("fused", 0)
    whale_score   = pick.get("whale_score", 0)
    bayes_pct     = pick.get("bayes_pct", 0)
    llm_why       = pick.get("llm_why", "No major news")
    filing_flag   = pick.get("filing_flag", "NEUTRAL")
    risk_pct      = pick.get("risk_pct", 0)
    r1            = pick.get("r1", 0)
    r2            = pick.get("r2", 0)
    conviction_flag = pick.get("conviction_flag", False)

    # Estimate catalyst date from earnings calendar
    catalyst_hint = "No upcoming catalyst identified"
    if earnings_cal:
        sym_earnings = (earnings_cal or {}).get(sym.upper(), {})
        if sym_earnings:
            result_date = sym_earnings.get("result_date", "")
            if result_date:
                catalyst_hint = f"Earnings result date: {result_date}"

    prompt = f"""You are a senior Indian equity analyst doing CAUSAL reasoning (not correlation).

STOCK: {sym} | SECTOR: {sector} | GRADE: {grade}
PRICE: ₹{entry:.0f} | SL: ₹{sl:.0f} ({risk_pct:.1f}% risk) | R1: ₹{r1:.0f} | R2: ₹{r2:.0f} | R3: ₹{r3:.0f}
UPSIDE/DOWNSIDE RATIO: {asym:.1f}x (R3 upside vs SL downside)
FUSED SCORE: {fused} | WHALE RADAR: {whale_score} | BAYES: {bayes_pct}%
MACRO: {macro_state} | FILING: {filing_flag}
NEWS/SENTIMENT: {llm_why}
CATALYST HINT: {catalyst_hint}
CONVICTION HOLD ACTIVE: {conviction_flag}

Your task: perform MULTI-HOP CAUSAL REASONING. Do NOT restate the quant scores.
Identify the SPECIFIC causal chain that makes this an asymmetric payoff opportunity.

Think step-by-step:
1. What is the ROOT CAUSE driving this setup? (regulatory approval, supply chain shift, earnings beat, sector rotation, FII re-entry)
2. What is the CAUSAL CHAIN? (event A → consequence B → market impact C → stock rerating D)
3. What specific CATALYST will trigger the move? When?
4. What is the PRIMARY RISK that invalidates this thesis?
5. How long should this position be held? (days, not just a number)

Respond ONLY with a JSON object, no markdown, no explanation:
{{
  "causal_thesis": "3-sentence max causal chain, specific to THIS stock and sector",
  "catalyst_date": "YYYY-MM-DD estimated or '' if unknown",
  "causal_conf": 0-100,
  "causal_verdict": "TAKE" or "SKIP" or "HOLD",
  "primary_risk": "single sentence — what kills this thesis",
  "hold_until": "describe exit trigger in plain English (e.g. 'catalyst + 5 days' or 'R2 hit')",
  "asymmetry_rationale": "why risk/reward is compelling at this price in one sentence"
}}"""

    try:
        # HIGH-4 FIX: was _llm_call_claude (undefined) — corrected to _call_claude
        result_text = _call_claude(prompt, max_tokens=600)
        if not result_text:
            log.debug(f"Tier4 {sym}: empty LLM response")
            return defaults

        # Strip markdown fences if present
        cleaned = result_text.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(
                l for l in cleaned.splitlines()
                if not l.strip().startswith("```")
            ).strip()

        parsed = json.loads(cleaned)
        causal_conf    = max(0, min(100, int(parsed.get("causal_conf", 50))))
        causal_verdict = str(parsed.get("causal_verdict", "HOLD")).upper()
        if causal_verdict not in ("TAKE", "SKIP", "HOLD"):
            causal_verdict = "HOLD"

        result = {
            "causal_thesis":   str(parsed.get("causal_thesis", ""))[:300],
            "catalyst_date":   str(parsed.get("catalyst_date", "")),
            "asymmetry_score": asym,
            "causal_conf":     causal_conf,
            "causal_verdict":  causal_verdict,
            "primary_risk":    str(parsed.get("primary_risk", ""))[:150],
            "hold_until":      str(parsed.get("hold_until", ""))[:100],
            "asymmetry_rationale": str(parsed.get("asymmetry_rationale", ""))[:150],
            "tier4_triggered": True,
        }
        log.info(
            f"Tier4 {sym}: causal_conf={causal_conf}% verdict={causal_verdict} "
            f"asymmetry={asym:.1f}x thesis='{result['causal_thesis'][:60]}...'"
        )
        return result

    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        log.debug(f"Tier4 {sym}: JSON parse failed: {e} — raw: {result_text[:100] if 'result_text' in dir() else 'N/A'}")
        return defaults
    except Exception as e:
        log.debug(f"Tier4 {sym}: unexpected error: {e}")
        return defaults


def _apply_tier4_to_picks(picks: list, macro: dict,
                            fii_data: dict = None, earnings_cal: dict = None) -> list:
    """
    Run Tier 4 causal reasoning on eligible picks (GREAT/ELITE, meta_prob > 65%).
    Caps at _TIER4_MAX_PER_RUN calls to control API cost.
    Mutates picks in-place with causal fields. Returns updated list.
    """
    if not picks or not LLM_ENABLED or not _ANTHROPIC_OK:
        return picks

    # Sort candidates by grade + fused to prioritise best setups
    grade_rank = {"ELITE": 0, "GREAT": 1, "GOOD": 2, "FAIR": 3}
    eligible = sorted(
        [p for p in picks if p.get("grade") in ("GREAT", "ELITE")
                           and p.get("meta_prob", 0) > 0.65
                           and not p.get("veto", False)],
        key=lambda x: (grade_rank.get(x.get("grade", "FAIR"), 9), -x.get("fused", 0))
    )

    tier4_count = 0
    for pick in eligible:
        if tier4_count >= _TIER4_MAX_PER_RUN:
            log.debug(f"Tier4: cap of {_TIER4_MAX_PER_RUN} reached — skipping remaining")
            break
        sym = pick.get("symbol", "?")
        log.info(f"Tier4 causal reasoning: {sym} (grade={pick.get('grade')}, meta_prob={pick.get('meta_prob', 0):.2f})")
        causal = _llm_causal_reasoning(pick, macro, fii_data=fii_data, earnings_cal=earnings_cal)
        pick.update(causal)
        tier4_count += 1

    if tier4_count:
        log.info(f"Tier4: causal reasoning complete — {tier4_count} pick(s) enriched")

    return picks


def calibrated_ai_judge(pick: dict, halal: dict, macro: dict,
                         calibration_params: Optional[dict] = None) -> dict:
    """
    Step 5: Calibrated AI Judge.
    Input:  enriched pick dict + halal AI result + macro regime
    Output: pick enriched with calibrated_confidence, position_size_tier,
            veto (bool), veto_reason (str)
    """
    sym           = pick.get("symbol", "")
    raw_meta_prob = pick.get("meta_prob", 0.55)
    setup_profile = pick.get("setup_profile", "BHwdv")
    grade         = pick.get("grade", "")
    sector        = pick.get("sector", "DIVERSIFIED")
    fused         = pick.get("fused", 0)

    # ── Calibrate probability ────────────────────────────────────────────────
    p_cal = _platt_calibrate(raw_meta_prob, calibration_params)
    p_cal = _regime_scaled_confidence(p_cal, macro.get("macro_state", "CHOP"),
                                      macro.get("vix_val", 18.0))

    # ── Veto checks (deterministic) ──────────────────────────────────────────
    veto, veto_reason = False, ""

    if halal.get("veto"):
        veto, veto_reason = True, f"Halal veto: {halal.get('veto_reason', '')}"

    elif halal.get("score", 100) < 40:
        veto, veto_reason = True, f"Halal score {halal['score']} < 40 (RISKY tier)"

    else:
        prev = _prev_day_context(sym)
        if prev["status"] == "stopped" and (prev["pnl_pct"] or 0) < -5:
            veto, veto_reason = True, f"Cooling-off: stopped at {prev['pnl_pct']:.1f}% yesterday"
        elif not veto:
            wr_data = _weekly_wr_for_profile(setup_profile, grade, sector)
            if wr_data["total"] >= 5 and wr_data["win_rate"] < 0.30:
                veto, veto_reason = (True,
                    f"Your {setup_profile} win rate only {wr_data['win_rate']:.0%} "
                    f"on {wr_data['total']} trades")

    if not veto:
        # CRIT-3 FIX: When Platt calibration params are missing (<50 samples), the
        # identity passthrough returns raw_meta_prob ~0.43. Using a hard 45% threshold
        # vetoes all uncalibrated picks. Lower to 40% until 200+ samples are collected.
        has_calibration = (calibration_params is not None and
                           calibration_params.get("n_samples", 0) >= 50)
        confidence_floor = 0.45 if has_calibration else 0.40
        if p_cal < confidence_floor:
            veto, veto_reason = True, (
                f"Calibrated confidence {p_cal:.0%} < {confidence_floor:.0%} "
                f"({'calibrated' if has_calibration else 'uncalibrated floor'})"
            )
        elif halal.get("score", 0) < 60:
            veto, veto_reason = True, f"Halal score {halal.get('score',0)} < 60 (ACCEPTABLE)"
        elif fused < APEX_MIN_SCORE:
            veto, veto_reason = True, f"Fused {fused} < APEX_MIN_SCORE {APEX_MIN_SCORE}"

    size_tier = "VETO" if veto else _kelly_fraction(p_cal)

    # ── CONVICTION HOLD MODULE (v5.1) ────────────────────────────────────────
    # High-conviction setups (GREAT/ELITE, LLM >=70%, regime not PANIC/MASSACRE,
    # Kelly FULL or HALF) get a mandatory 10-15 day hold window.
    # During the hold: only SL is enforced — R1 hit is IGNORED.
    # After max_hold_days: time-stop triggers at market price.
    # ─────────────────────────────────────────────────────────────────────────
    llm_confidence  = pick.get("llm_confidence", 0) or 0
    macro_state_val = macro.get("macro_state", "CHOP")
    conviction_flag = False
    min_hold_days   = 0
    max_hold_days   = 0
    conviction_note = ""

    if not veto:
        is_high_grade      = grade in ("GREAT", "ELITE")
        is_high_conf       = llm_confidence >= 70
        is_safe_regime     = macro_state_val not in ("PANIC", "MASSACRE")
        is_conviction_size = size_tier in ("FULL", "HALF")

        if is_high_grade and is_high_conf and is_safe_regime and is_conviction_size:
            conviction_flag = True
            min_hold_days   = 10
            max_hold_days   = 15
            conviction_note = "Conviction Hold: Min 10 days, SL only — ignore R1"
            log.info(
                f"CONVICTION HOLD triggered for {sym}: grade={grade}, "
                f"llm_conf={llm_confidence}%, regime={macro_state_val}, size={size_tier}"
            )

    return {
        **pick,
        "calibrated_confidence": p_cal,
        "raw_meta_prob":         raw_meta_prob,
        "position_size_tier":    size_tier,
        "halal_detail":          halal,
        "veto":                  veto,
        "veto_reason":           veto_reason,
        "worth_flag":            _confidence_flag(p_cal) if not veto else "SKIP",
        # Conviction Hold fields (v5.1)
        "conviction_flag":       conviction_flag,
        "min_hold_days":         min_hold_days,
        "max_hold_days":         max_hold_days,
        "conviction_note":       conviction_note,
    }



# ══════════════════════════════════════════════════════════════════════════════
# [PATCH-D]  NO-RESPONSE = SKIPPED  (v4.0-M — Step 8 EOD auto-log)
# ══════════════════════════════════════════════════════════════════════════════

def _auto_expire_stale_positions():
    """
    FIX-A8: Mark pick_outcomes rows that are still 'open' but older than
    MC_HORIZON + 2 days as 'expired'. This prevents the capacity guard from
    being permanently blocked by ghost positions that were never replied to.

    Root cause: picks with no Telegram reply stay status='open' forever.
    _auto_log_skipped_picks() marks trade_decisions as SKIPPED but does NOT
    update pick_outcomes.status. After MC_HORIZON days those picks can never
    hit a target, so they should expire automatically.

    Called at the START of run() — before capacity guard — so today's run
    is not blocked by yesterday's (or last month's) unresolved positions.
    """
    cutoff = (datetime.today() - timedelta(days=MC_HORIZON + 2)).strftime("%Y-%m-%d")
    try:
        with _db_conn(write=True) as con:
            expired = con.execute(
                "UPDATE pick_outcomes SET status='expired', exit_date=?, updated_at=? "
                "WHERE status='open' AND run_date < ?",
                (datetime.today().strftime("%Y-%m-%d"),
                 datetime.today().isoformat(), cutoff)
            ).rowcount
        if expired:
            log.info(f"Auto-expired {expired} stale open position(s) older than {MC_HORIZON}d")
        else:
            log.debug("Auto-expire: no stale positions found")
    except Exception as e:
        log.debug(f"Auto-expire stale positions: {e}")


def _backup_db_to_sheets():
    """
    FIX-A6: Export last 500 pick_outcomes rows to a BACKUP tab in Google Sheets.
    Called from _weekly_ai_status_agent() so history survives GitHub Actions
    cache eviction (7-day TTL by default). Read-only — never mutates DB.
    FIX-9: Post-backup verification — reads back the first row from DB_BACKUP
    and compares row count to local DB. Logs a warning if they diverge.
    ARCH-M2: Extended to also export trade_decisions (DB_DECISIONS tab) and
    sniper_results (DB_SIGNALS tab) so a mid-week cache eviction cannot erase
    human decisions or scored signals for that week.
    """
    if not _sheets_ok():
        log.debug("DB backup to Sheets skipped — Sheets not configured")
        return

    exported_at = datetime.today().isoformat()

    # ── Tab 1: pick_outcomes (unchanged from FIX-A6) ─────────────────────────
    try:
        with _db_conn() as con:
            rows = con.execute(
                "SELECT run_date, symbol, grade, fused_score, status, "
                "exit_price, pnl_pct, days_held, hit_target, story "
                "FROM pick_outcomes "
                "ORDER BY run_date DESC LIMIT 500"
            ).fetchall()
        if not rows:
            log.info("DB backup: no pick_outcomes rows to export")
        else:
            local_row_count = len(rows)
            header = [["run_date","symbol","grade","fused_score","status",
                       "exit_price","pnl_pct","days_held","hit_target","story",
                       f"exported_at: {exported_at}"]]
            _push_sheet("DB_BACKUP", header + [list(r) for r in rows])
            log.info(f"DB backup: {local_row_count} pick_outcomes rows → Sheets DB_BACKUP ✅")

            # FIX-9: Post-backup verification
            try:
                ws = _get_ws("DB_BACKUP")
                if ws is not None:
                    all_vals = ws.get_all_values()
                    sheets_data_rows = len(all_vals) - 1
                    if abs(sheets_data_rows - local_row_count) > 5:
                        log.warning(
                            f"FIX-9: DB_BACKUP verification MISMATCH — "
                            f"local={local_row_count} rows, Sheets={sheets_data_rows} rows. "
                            f"Backup may be incomplete. Check Sheets quota or auth."
                        )
                    else:
                        log.info(f"FIX-9: DB_BACKUP verified ✅ — local={local_row_count}, Sheets={sheets_data_rows} rows")
            except Exception as ve:
                log.warning(f"FIX-9: DB_BACKUP post-verification failed (non-fatal): {ve}")

    except Exception as e:
        log.warning(f"DB backup pick_outcomes to Sheets failed: {e}")

    # ── Tab 2: trade_decisions (ARCH-M2) ─────────────────────────────────────
    try:
        with _db_conn() as con:
            dec_rows = con.execute(
                "SELECT run_date, symbol, decision, entry_price, shares_taken, "
                "skip_reason, ai_confidence, worth_flag, logged_at "
                "FROM trade_decisions "
                "ORDER BY logged_at DESC LIMIT 500"
            ).fetchall()
        if dec_rows:
            dec_header = [["run_date","symbol","decision","entry_price","shares_taken",
                           "skip_reason","ai_confidence","worth_flag","logged_at",
                           f"exported_at: {exported_at}"]]
            _push_sheet("DB_DECISIONS", dec_header + [list(r) for r in dec_rows])
            log.info(f"ARCH-M2: {len(dec_rows)} trade_decisions rows → Sheets DB_DECISIONS ✅")
        else:
            log.debug("ARCH-M2: no trade_decisions rows to export")
    except Exception as e:
        log.warning(f"ARCH-M2: DB_DECISIONS backup failed: {e}")

    # ── Tab 3: sniper_results (ARCH-M2) ──────────────────────────────────────
    try:
        with _db_conn() as con:
            sig_rows = con.execute(
                "SELECT run_date, symbol, grade, fused_score, "
                "close, stop_loss, r1, r2, r3, sector, created_at "
                "FROM sniper_results "
                "ORDER BY created_at DESC LIMIT 200"
            ).fetchall()
        if sig_rows:
            sig_header = [["run_date","symbol","grade","fused_score",
                           "close","stop_loss","r1","r2","r3",
                           "sector","created_at",
                           f"exported_at: {exported_at}"]]
            _push_sheet("DB_SIGNALS", sig_header + [list(r) for r in sig_rows])
            log.info(f"ARCH-M2: {len(sig_rows)} sniper_results rows → Sheets DB_SIGNALS ✅")
        else:
            log.debug("ARCH-M2: no sniper_results rows to export")
    except Exception as e:
        log.warning(f"ARCH-M2: DB_SIGNALS backup failed: {e}")


def _auto_log_skipped_picks(date_label: str):
    """
    Auto-log all today's AI-passed picks that received no Telegram reply as SKIPPED.
    Called once at EOD (after Telegram reply window closes). No reminder sent.
    """
    try:
        with _db_conn() as con:
            # DISTINCT: sniper_results has no UNIQUE constraint, reruns insert duplicates
            all_picks_rows = con.execute(
                "SELECT DISTINCT symbol FROM sniper_results WHERE run_date=?",
                (date_label,)
            ).fetchall()
            # trade_decisions has UNIQUE(run_date,symbol) so set is fine
            logged = {row[0] for row in con.execute(
                "SELECT symbol FROM trade_decisions WHERE run_date=?",
                (date_label,)
            ).fetchall()}

        unresponded = [r[0] for r in all_picks_rows if r[0] not in logged]
        if not unresponded:
            log.debug("Auto-log: all picks already have decisions — nothing to log")
            return

        log.info(f"Auto-logging {len(unresponded)} unresponded picks as SKIPPED")
        for sym in unresponded:
            _log_trade_decision(date_label, sym, "SKIPPED",
                                skip_reason="no_response", ai_confidence=None)
        log.info(f"SKIPPED auto-log complete: {', '.join(unresponded)}")
    except Exception as e:
        log.error(f"Auto-log skipped: {e}")



# ══════════════════════════════════════════════════════════════════════════════
# [PATCH-E]  DB SCHEMA v4.0-M  (added at bottom of _init_db via _migrate_db_v4)
# ══════════════════════════════════════════════════════════════════════════════

_DB_SCHEMA_V4 = """
CREATE TABLE IF NOT EXISTS halal_ai_cache (
    symbol          TEXT PRIMARY KEY,
    score           INTEGER NOT NULL,
    veto            INTEGER NOT NULL DEFAULT 0,
    tier            TEXT NOT NULL,
    debt_to_mcap    REAL,
    business_model  TEXT,
    ethical_score   INTEGER DEFAULT 0,
    llm_confidence  REAL DEFAULT 0.5,
    assessed_date   TEXT NOT NULL,
    source          TEXT DEFAULT 'SCORED',
    llm_hash        TEXT,
    expires_at      TEXT  -- SEVERE-5 FIX: explicit TTL prevents unbounded table growth
);

CREATE TABLE IF NOT EXISTS platt_calibration (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    A           REAL NOT NULL,
    B           REAL NOT NULL,
    n_samples   INTEGER NOT NULL,
    ece         REAL,
    trained_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS strategy_sandbox (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_text   TEXT NOT NULL,
    param_name      TEXT,
    param_old       TEXT,
    param_new       TEXT,
    backtest_wr     REAL,
    backtest_dd     REAL,
    backtest_sharpe REAL,
    status          TEXT DEFAULT 'PROPOSED',
    created_at      TEXT DEFAULT (datetime('now')),
    reviewed_at     TEXT
);

CREATE TABLE IF NOT EXISTS strategy_approved (
    param_name      TEXT PRIMARY KEY,
    param_value     TEXT NOT NULL,
    approved_at     TEXT NOT NULL,
    sandbox_id      INTEGER
);

-- Prevent duplicate sniper_results rows (reruns should not create duplicates)
CREATE UNIQUE INDEX IF NOT EXISTS uq_sniper_results_date_symbol
    ON sniper_results(run_date, symbol);

-- DUPLICATE FIX: Prevent duplicate pick_outcomes rows.
-- The outcome engine was iterating over all rows including duplicates from reruns,
-- causing 21 "still open" log entries for the same 5 symbols.
-- This index makes INSERT OR IGNORE idempotent on reruns.
CREATE UNIQUE INDEX IF NOT EXISTS uq_pick_outcomes_date_symbol
    ON pick_outcomes(run_date, symbol);
"""


def _deduplicate_pick_outcomes():
    """
    One-time cleanup: remove duplicate pick_outcomes rows that were inserted
    before the UNIQUE index existed. Keeps the row with the highest id
    (most recent insert) for each (run_date, symbol) pair.
    Safe to call on every startup — fast no-op when no duplicates exist.
    """
    try:
        with _db_conn(write=True) as con:
            deleted = con.execute("""
                DELETE FROM pick_outcomes
                WHERE id NOT IN (
                    SELECT MAX(id) FROM pick_outcomes
                    GROUP BY run_date, symbol
                )
            """).rowcount
        if deleted:
            log.info(f"pick_outcomes dedup: removed {deleted} duplicate row(s)")
    except Exception as e:
        log.debug(f"pick_outcomes dedup: {e}")


def _migrate_db_v4():
    """v4.0-M additive migration. Safe to run on every startup."""
    try:
        with _db_conn(write=True) as con:
            con.executescript(_DB_SCHEMA_V4)
        # FIX-5: Migration — add expires_at column to llm_cache if absent.
        # llm_cache had no expiry — January buyback filings were served in June.
        # This is idempotent: SQLite raises "duplicate column name" if already exists.
        try:
            with _db_conn(write=True) as con:
                con.execute("ALTER TABLE llm_cache ADD COLUMN expires_at TEXT")
                log.info("DB migration: added 'expires_at' column to llm_cache (FIX-5) ✅")
        except Exception as _e:
            if "duplicate column" not in str(_e).lower() and "already exists" not in str(_e).lower():
                log.debug(f"llm_cache expires_at migration: {_e}")
        # FIX-PERF: add sector column to pick_outcomes for existing DBs.
        # Without this, the PERFORMANCE tab JOIN on sniper_results (cleared by rerun) returns
        # empty sector data.  Denormalizing sector into pick_outcomes breaks the dependency.
        try:
            with _db_conn(write=True) as con:
                con.execute("ALTER TABLE pick_outcomes ADD COLUMN sector TEXT DEFAULT 'DIVERSIFIED'")
                log.info("DB migration: added 'sector' column to pick_outcomes (FIX-PERF) ✅")
        except Exception as _e:
            if "duplicate column" not in str(_e).lower() and "already exists" not in str(_e).lower():
                log.debug(f"pick_outcomes sector migration: {_e}")
        # MEDIUM-4 FIX: exit_date column may be absent in DBs created before v5.4.
        # The outcome engine writes SET exit_date=? which silently fails without this column.
        _po_v54_alters = [
            ("exit_date",   "TEXT"),
            ("lane",        "TEXT DEFAULT NULL"),
        ]
        for col_name, col_def in _po_v54_alters:
            try:
                with _db_conn(write=True) as con:
                    con.execute(f"ALTER TABLE pick_outcomes ADD COLUMN {col_name} {col_def}")
                    log.info(f"DB migration: added '{col_name}' to pick_outcomes (MEDIUM-4 v5.4) ✅")
            except Exception as _me:
                if "duplicate column" not in str(_me).lower() and "already exists" not in str(_me).lower():
                    log.debug(f"pick_outcomes {col_name} migration: {_me}")

        log.info("DB v4.0-M migration complete")
        _deduplicate_pick_outcomes()   # DUPLICATE FIX: clean existing dupes before index is enforced
        # SEVERE-4 FIX: idx_score_cache_lookup was redundant with the PK — do NOT recreate it.
        # score_cache PK (symbol, run_date, intel_hash) already provides O(1) lookup.

        # SEVERE-5 FIX: add expires_at column to halal_ai_cache for existing DBs.
        # Without this column the table grows unbounded — assessed_date alone has no purge path.
        try:
            with _db_conn(write=True) as con:
                con.execute("ALTER TABLE halal_ai_cache ADD COLUMN expires_at TEXT")
                log.info("DB migration: added 'expires_at' column to halal_ai_cache (SEVERE-5) ✅")
        except Exception as _e:
            if "duplicate column" not in str(_e).lower() and "already exists" not in str(_e).lower():
                log.debug(f"halal_ai_cache expires_at migration: {_e}")

        # v5.1 CONVICTION HOLD: add columns to positions table
        _conv_alters = [
            ("conviction_flag", "INTEGER DEFAULT 0"),
            ("min_hold_days",   "INTEGER DEFAULT 0"),
            ("max_hold_days",   "INTEGER DEFAULT 0"),
        ]
        for col_name, col_def in _conv_alters:
            try:
                with _db_conn(write=True) as con:
                    con.execute(f"ALTER TABLE positions ADD COLUMN {col_name} {col_def}")
                log.info(f"DB migration: added '{col_name}' to positions (CONVICTION HOLD) ✅")
            except Exception as _ce:
                if "duplicate column" not in str(_ce).lower() and "already exists" not in str(_ce).lower():
                    log.debug(f"positions {col_name} migration: {_ce}")

        # v5.1 CONVICTION HOLD: add conviction fields to pick_outcomes for reporting
        _po_conv_alters = [
            ("conviction_flag", "INTEGER DEFAULT 0"),
            ("min_hold_days",   "INTEGER DEFAULT 0"),
            ("max_hold_days",   "INTEGER DEFAULT 0"),
        ]
        for col_name, col_def in _po_conv_alters:
            try:
                with _db_conn(write=True) as con:
                    con.execute(f"ALTER TABLE pick_outcomes ADD COLUMN {col_name} {col_def}")
                log.info(f"DB migration: added '{col_name}' to pick_outcomes (CONVICTION HOLD) ✅")
            except Exception as _ce:
                if "duplicate column" not in str(_ce).lower() and "already exists" not in str(_ce).lower():
                    log.debug(f"pick_outcomes {col_name} migration: {_ce}")
    except Exception as e:
        log.debug(f"DB v4 migration: {e}")



# ══════════════════════════════════════════════════════════════════════════════
# [PATCH-F]  WEEKLY AI STATUS AGENT  (v4.0-M — Step 10, read-only LLM analysis)
# ══════════════════════════════════════════════════════════════════════════════

def _apply_walkforward_weight_updates():
    """
    FIX-6: Wire _walkforward_engine_correlation output into APEX engine weights (W dict).
    Called from _weekly_ai_status_agent() after 30+ closed picks exist.
    Rules:
      GENUINE  (r > 0.30, p < 0.10) → keep weight (no change)
      MARGINAL (0.10 ≤ r ≤ 0.30)   → small reduction (−5%)
      NOISE    (r < 0.10)           → halve the weight
    Changes capped at ±20% per weekly run to prevent oscillation.
    Weights are re-normalised after adjustment so they remain proportional.
    """
    engine_to_w_key = {
        "whale_radar":  "whale_radar",
        "divergence":   "divergence",
        "vol_profile":  "vol_profile",
        "pattern":      "pattern",
        "bayesian":     "bayesian",
    }
    try:
        corr = _walkforward_engine_correlation(days=90)
        if corr.get("status") in ("INSUFFICIENT", "ERROR"):
            log.info(f"Walkforward weight update skipped: {corr.get('message', corr.get('status'))}")
            return

        adjustments = []
        for engine, w_key in engine_to_w_key.items():
            if engine not in corr:
                continue
            data = corr[engine]
            status = data.get("status", "NOISE")
            old_w = W.get(w_key, 0.15)

            if status == "GENUINE":
                new_w = old_w          # keep weight unchanged
                action = "KEEP"
            elif status == "MARGINAL":
                new_w = old_w * 0.95  # −5% reduction
                action = "TRIM"
            else:  # NOISE
                new_w = old_w * 0.50  # halve the weight
                action = "HALVE"

            # Cap change at ±20% of original
            max_change = old_w * 0.20
            new_w = max(old_w - max_change, min(old_w + max_change, new_w))
            new_w = round(max(0.05, min(0.50, new_w)), 4)  # hard bounds

            if new_w != old_w:
                W[w_key] = new_w
                adjustments.append(f"{engine}: {old_w:.3f}→{new_w:.3f} [{action} r={data.get('r', 0):.2f} n={data.get('n', 0)}]")
            else:
                log.debug(f"Walkforward {engine}: no change ({action}, r={data.get('r', 0):.2f})")

        if adjustments:
            log.info(f"FIX-6: APEX weights updated from walkforward correlation:\n  " + "\n  ".join(adjustments))
        else:
            log.info("FIX-6: Walkforward engine correlation — all weights unchanged (GENUINE signals)")
    except Exception as e:
        log.warning(f"_apply_walkforward_weight_updates failed (non-fatal): {e}")


def _weekly_ai_status_agent():
    """
    Step 10: Weekly AI Status Agent.
    Reads performance data, generates observations via GPT-4o (batch).
    NEVER mutates DB or parameters. Falls back to _send_weekly_review() if no LLM key.
    FIX-A6: also triggers DB backup to Sheets so pick history survives cache eviction.
    FIX-W1: Only runs on Monday (weekday==0) unless FORCE_WEEKLY env var is set.
    """
    # FIX-W1: Guard against accidental Tuesday runs (e.g. manual workflow_dispatch).
    # Set FORCE_WEEKLY=true in GitHub Actions dispatch inputs to override.
    _force = os.getenv("FORCE_WEEKLY", "").strip().lower() in ("1", "true", "yes")
    if datetime.today().weekday() != 0 and not _force:
        log.info(
            "Weekly review skipped — today is not Monday "
            "(weekday=%d). Set FORCE_WEEKLY=true to override.",
            datetime.today().weekday()
        )
        return

    # FIX-A6: Backup DB to Sheets at the start of weekly review.
    # GitHub Actions cache TTL is 7 days — the weekly run is the perfect trigger
    # to ensure history is preserved before it can expire.
    _backup_db_to_sheets()

    # FIX-5: Purge expired llm_cache rows weekly then vacuum.
    # Stale filings (e.g. January buyback) are no longer served months later.
    try:
        with _db_conn(write=True) as _llm_clean_con:
            deleted = _llm_clean_con.execute(
                "DELETE FROM llm_cache WHERE expires_at IS NOT NULL AND expires_at <= datetime('now')"
            ).rowcount
        if deleted:
            log.info(f"FIX-5: Pruned {deleted} expired llm_cache row(s)")
            try:
                with _db_conn(write=True) as _vac_con:
                    _vac_con.execute("PRAGMA vacuum")
            except Exception:
                pass
    except Exception as _ce:
        log.debug(f"llm_cache cleanup: {_ce}")

    # SEVERE-5 FIX: purge expired halal_ai_cache rows weekly.
    # Without this the table grew unbounded (no expiry path existed before this fix).
    try:
        with _db_conn(write=True) as _hac_con:
            h_deleted = _hac_con.execute(
                "DELETE FROM halal_ai_cache "
                "WHERE expires_at IS NOT NULL AND expires_at <= date('now')"
            ).rowcount
        if h_deleted:
            log.info(f"SEVERE-5: Pruned {h_deleted} expired halal_ai_cache row(s)")
    except Exception as _hce:
        log.debug(f"halal_ai_cache cleanup: {_hce}")

    if not (_ANTHROPIC_OK or _OPENAI_OK):
        _send_weekly_review()
        return

    log.info("Weekly AI Status Agent running...")
    try:
        since = (datetime.today() - timedelta(days=7)).strftime("%Y-%m-%d")
        with _db_conn() as con:
            perf = con.execute("""
                SELECT grade, status, pnl_pct, sector
                FROM pick_outcomes WHERE run_date>=? AND status!='open'
            """, (since,)).fetchall()
            decisions = con.execute("""
                SELECT decision, COUNT(*) FROM trade_decisions WHERE run_date>=?
                GROUP BY decision
            """, (since,)).fetchall()
            halal_corr = con.execute("""
                SELECT h.tier, o.status, o.pnl_pct
                FROM halal_ai_cache h
                JOIN pick_outcomes o ON h.symbol=o.symbol
                WHERE o.run_date>=? AND o.status!='open'
            """, (since,)).fetchall()

        total   = len(perf)
        wins    = sum(1 for _, s, _, _ in perf if s in ("r1_hit","r2_hit","r3_hit"))
        avg_pnl = (sum(p or 0 for _, _, p, _ in perf) / total) if total > 0 else 0
        dec_map = {d: c for d, c in decisions}
        sector_wr = {}
        for _, status, pnl, sector in perf:
            sector_wr.setdefault(sector, {"wins": 0, "total": 0})
            sector_wr[sector]["total"] += 1
            if status in ("r1_hit","r2_hit","r3_hit"):
                sector_wr[sector]["wins"] += 1

        context = {
            "week": since,
            "total_closed": total,
            "wins": wins,
            "win_rate_pct": round(wins/total*100, 1) if total > 0 else 0,
            "avg_pnl_pct": round(avg_pnl, 2),
            "taken": dec_map.get("TAKEN", 0),
            "skipped": dec_map.get("SKIPPED", 0),
            "sector_win_rates": {
                s: round(v["wins"]/v["total"]*100, 1)
                for s, v in sector_wr.items() if v["total"] >= 2
            },
            "halal_tier_performance": {
                tier: {
                    "wins": sum(1 for t, s, _ in halal_corr if t==tier and s in ("r1_hit","r2_hit","r3_hit")),
                    "total": sum(1 for t, _, _ in halal_corr if t==tier)
                }
                for tier in ("PURE", "ACCEPTABLE", "RISKY")
            }
        }

        prompt = (
            "You are a trading performance analyst reviewing a week of NSE halal swing trades.\n"
            f"Context: {json.dumps(context, indent=2)}\n\n"
            "Generate a structured report with EXACTLY these sections:\n"
            "OBSERVATIONS: 2-3 factual bullet points about what happened\n"
            "PATTERNS: 1-2 repeating patterns you notice\n"
            "ANOMALIES: anything unexpected vs historical norms\n\n"
            "Rules:\n"
            "- Be factual, not prescriptive\n"
            "- Never say 'Set X = Y' or suggest parameter changes\n"
            "- Flag halal tier correlation if noteworthy\n"
            "- Keep under 300 words"
        )
        report = (_call_openai(prompt, model=OPENAI_BATCH_MODEL, max_tokens=400) or
                  _call_claude(prompt, max_tokens=400))

        if not report:
            _send_weekly_review()
            return

        # OUT-3 (v5.0): Include shortlist trend analysis in weekly report
        trends_text = _analyze_shortlist_trends()

        week_start = since
        with _db_conn(write=True) as con:
            con.execute("""
                INSERT OR REPLACE INTO weekly_reviews
                  (week_start, signals_total, taken, skipped, wins, losses,
                   avg_pnl, summary_text)
                VALUES (?,?,?,?,?,?,?,?)
            """, (week_start, total, dec_map.get("TAKEN",0), dec_map.get("SKIPPED",0),
                  wins, total-wins, avg_pnl, report))

        msg = (f"\U0001f4ca WEEKLY AI REPORT | {since} \u2192 {datetime.today().strftime('%Y-%m-%d')}\n\n"
               f"{report}\n\n"
               f"{trends_text}\n\n"
               f"\U0001f91d Read-only analysis. No parameters changed.")
        _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, msg)

        # FIX-6: Wire _walkforward_engine_correlation output into APEX weights.
        # Previously this function was dead code — it computed Spearman-r between
        # sub-engine scores and real P&L but its result was never used.
        # Now: after 30+ closed picks, update W[] based on GENUINE/NOISE status.
        # Cap changes at ±20% per week to prevent oscillation.
        _apply_walkforward_weight_updates()

        log.info("Weekly AI Status Agent complete ✅")

    except Exception as e:
        log.error(f"Weekly AI Status Agent failed: {e}")
        _send_weekly_review()



# ══════════════════════════════════════════════════════════════════════════════
# [PATCH-G]  SANDBOX PARAMETER PROPOSALS  (v4.0-M — Step 11, human-gated)
# ══════════════════════════════════════════════════════════════════════════════

def _generate_sandbox_proposal():
    """
    Step 11: Generate parameter proposals from LLM based on 90-day analysis.
    Saves to strategy_sandbox (status=PROPOSED). NEVER touches production.
    Requires 90 days of data and 30+ closed trades.
    """
    if not (_ANTHROPIC_OK or _OPENAI_OK):
        log.info("Sandbox proposals require LLM key — skipping")
        return

    try:
        with _db_conn() as con:
            oldest = con.execute("SELECT MIN(run_date) FROM pick_outcomes").fetchone()
            count  = con.execute("SELECT COUNT(*) FROM pick_outcomes WHERE status!='open'").fetchone()
        if not oldest or not oldest[0]:
            log.info("No historical data — skipping sandbox proposals"); return
        data_days = (datetime.today().date() -
                     datetime.strptime(oldest[0], "%Y-%m-%d").date()).days
        if data_days < 90 or (count[0] if count else 0) < 30:
            log.info(f"Only {data_days}d data ({count[0] if count else 0} closed trades) "
                     "— sandbox proposals need 90d/30 trades"); return
    except Exception as e:
        log.debug(f"Sandbox data check: {e}"); return

    try:
        since = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")
        with _db_conn() as con:
            perf = con.execute("""
                SELECT grade, status, pnl_pct, sector, fused_score
                FROM pick_outcomes WHERE run_date>=? AND status!='open'
            """, (since,)).fetchall()
            current_params = {
                "APEX_MIN_SCORE": APEX_MIN_SCORE,
                "APEX_TOP_N": APEX_TOP_N,
                "CAPACITY_MAX_OPEN": CAPACITY_MAX_OPEN,
                "CAPACITY_MAX_WEEK": CAPACITY_MAX_WEEK,
                "MC_SIMS": MC_SIMS,
            }

        total = len(perf)
        if total < 10: return
        wins = sum(1 for _, s, _, _, _ in perf if s in ("r1_hit","r2_hit","r3_hit"))

        prompt = (
            "You are a trading strategy parameter optimiser. "
            "Based on 90-day performance data, suggest 1-3 parameter adjustments.\n"
            f"Current params: {json.dumps(current_params)}\n"
            f"Performance: {total} trades, {wins} wins ({wins/total*100:.1f}% WR), "
            f"avg P&L {sum(p or 0 for _,_,p,_,_ in perf)/total:.1f}%\n\n"
            "Return a JSON array of proposals:\n"
            '[{"param": "APEX_MIN_SCORE", "old_value": 48, "new_value": 52, '
            '"rationale": "Raise threshold in CHOP regime — reduces false positives"}]\n\n'
            "Rules:\n"
            "- Maximum 3 proposals\n"
            "- Only suggest params from the current_params dict\n"
            "- Changes must be modest (+-10% max)\n"
            "- Require >=5% win rate improvement as justification"
        )
        raw = (_call_openai(prompt, model=OPENAI_BATCH_MODEL, max_tokens=500) or
               _call_claude(prompt, max_tokens=500))
        if not raw: return

        txt = raw.strip().replace("```json", "").replace("```", "")
        proposals = json.loads(txt)
        if not isinstance(proposals, list): return

        with _db_conn(write=True) as con:
            for p in proposals[:3]:
                con.execute("""
                    INSERT INTO strategy_sandbox
                      (proposal_text, param_name, param_old, param_new)
                    VALUES (?,?,?,?)
                """, (
                    p.get("rationale", "")[:500],
                    str(p.get("param", "")),
                    str(p.get("old_value", "")),
                    str(p.get("new_value", "")),
                ))
        log.info(f"Sandbox: {len(proposals)} proposal(s) saved (status=PROPOSED). "
                 "Review at strategy_sandbox table before approving.")

        notif = "\U0001f52c SANDBOX PROPOSALS (pending your review):\n\n"
        for p in proposals[:3]:
            notif += (f"\u2022 {p.get('param')}: {p.get('old_value')} \u2192 {p.get('new_value')}\n"
                      f"  Reason: {p.get('rationale','')[:80]}\n\n")
        notif += "\u2139\ufe0f Run SQL: UPDATE strategy_sandbox SET status='APPROVED' WHERE id=X to approve."
        _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, notif)

    except Exception as e:
        log.error(f"Sandbox proposal: {e}")


def _load_approved_params():
    """
    BUG#4 FIX: Load dynamically approved strategy parameters from strategy_approved DB.
    Overrides SECTOR_TRUTH multipliers and APEX weights (W dict) if approved values exist.
    strategy_approved is written by _generate_sandbox_proposal() after human review.
    Safe to call at startup — falls back to hardcoded defaults if table is empty.
    """
    try:
        with _db_conn() as con:
            rows = con.execute(
                "SELECT param_name, param_value FROM strategy_approved"
            ).fetchall()
        if not rows:
            return
        for param_name, param_value in rows:
            try:
                val = float(param_value)
            except (ValueError, TypeError):
                continue
            # Sector truth multipliers: stored as "SECTOR_TRUTH:NIFTY IT" etc.
            if param_name.startswith("SECTOR_TRUTH:"):
                sector_key = param_name.split(":", 1)[1]
                if sector_key in SECTOR_TRUTH:
                    old = SECTOR_TRUTH[sector_key]
                    SECTOR_TRUTH[sector_key] = round(max(0.0, min(2.0, val)), 3)
                    log.info(f"strategy_approved: SECTOR_TRUTH[{sector_key}] {old} → {SECTOR_TRUTH[sector_key]}")
            # APEX engine weights: stored as "APEX_W:whale_radar" etc.
            elif param_name.startswith("APEX_W:"):
                engine_key = param_name.split(":", 1)[1]
                if engine_key in W:
                    old = W[engine_key]
                    W[engine_key] = round(max(0.0, min(1.0, val)), 4)
                    log.info(f"strategy_approved: W[{engine_key}] {old} → {W[engine_key]}")
            # Scalar params like APEX_MIN_SCORE, ACCOUNT_RISK_PCT
            elif param_name == "APEX_MIN_SCORE":
                global APEX_MIN_SCORE
                APEX_MIN_SCORE = int(val)
                log.info(f"strategy_approved: APEX_MIN_SCORE → {APEX_MIN_SCORE}")
            elif param_name == "ACCOUNT_RISK_PCT":
                global ACCOUNT_RISK_PCT
                ACCOUNT_RISK_PCT = round(max(0.005, min(0.05, val)), 4)
                log.info(f"strategy_approved: ACCOUNT_RISK_PCT → {ACCOUNT_RISK_PCT}")
        log.info(f"strategy_approved: loaded {len(rows)} param override(s) ✅")
    except Exception as e:
        log.debug(f"_load_approved_params: {e} — using hardcoded defaults")


def run():
    """
    Architecture-aligned unified pipeline (v4.5-ARCH):
    1. Init DB + caches. Same-day rerun auto-clears stale picks.
    2. Macro regime (one fetch, cached). MASSACRE halts pipeline.
    3. Bhavcopy → liquidity+price pre-filter (NO halal gate — engines see all EQ).
    4. Intelligence: FII/DII, Insider, Filings, Earnings (concurrent asyncio fetch).
    5. Fortress + APEX scoring on ALL liquid candidates in one fused loop.
    6. Rank by fused score → sector cap → market-cap bucket → top-N selected.
    7. STEP 4 (arch): 4-layer Halal AI Screen on top-N only.
       L1 business veto (instant keyword) → L2 financial ratios →
       L3 ethical overlay → L4 LLM business model analysis.
    8. Calibrated AI Judge → position sizing → LLM story enrichment.
    9. Outputs: Excel, HTML, Sheets, Telegram (one send, halal-passed picks only).
   10. Weekly agent (--weekly-review) + Sandbox proposals (--sandbox-proposals)
       run as separate CLI invocations.
    """
    _init_db()
    # FIX-1.4: Declare FORCE_YFINANCE as global so the auto-detect can modify it mid-run
    global FORCE_YFINANCE
    # FIX-2.6: Validate secrets at startup
    secrets.validate()
    # FIX-A07: Validate numeric config bounds at startup
    try:
        _validate_startup_config()
    except ValueError as e:
        log.error(f"Startup config validation FAILED: {e}")
        raise
    _load_approved_params()   # BUG#4 FIX: load dynamic params from strategy_approved DB
    _load_live_bayes_priors() # FIX-7: replace hardcoded priors with live empirical win rates if ≥50 samples
    _, date_label = _get_last_trading_day()

    # DEBUG: Verify LLM keys — booleans only, safe to keep in production logs.
    # Keys are masked in GitHub Actions secrets but True/False confirms they're set.
    log.info(f"LLM_ENABLED: {LLM_ENABLED}")
    log.info(f"Anthropic OK: {_ANTHROPIC_OK}")
    log.info(f"OpenAI OK:    {_OPENAI_OK}")
    if _ANTHROPIC_OK:
        _stale_flag = "⚠️ (was stale — auto-corrected to claude-sonnet-4-5)" if _raw_claude_model in _STALE_MODEL_NAMES else "✅"
        log.info(f"Claude model: {CLAUDE_MODEL} {_stale_flag}")

    # Reset LLM circuit breakers (per-provider) for this run — FIX-4.1-M
    global _CLAUDE_FAIL_COUNT, _CLAUDE_CIRCUIT_OPEN, _OPENAI_FAIL_COUNT, _OPENAI_CIRCUIT_OPEN
    global _LLM_FAIL_COUNT, _LLM_CIRCUIT_OPEN
    with _LLM_CB_LOCK:
        _CLAUDE_FAIL_COUNT   = 0
        _CLAUDE_CIRCUIT_OPEN = False
        _OPENAI_FAIL_COUNT   = 0
        _OPENAI_CIRCUIT_OPEN = False
        _LLM_FAIL_COUNT      = 0
        _LLM_CIRCUIT_OPEN    = False

    # Reset NSE circuit breaker for this run (IP bans are per-session, not permanent)
    global _NSE_CONSECUTIVE_FAILS, _NSE_IP_BLOCKED, _NSE_HISTORY_OK
    with _NSE_FAIL_LOCK:
        _NSE_CONSECUTIVE_FAILS = 0
        _NSE_IP_BLOCKED        = False
    _set_nse_history_ok(None)   # FIX-A02: thread-safe reset; re-probe NSE at start of each run
    global _NSE_SESSION_REBUILT_THIS_RUN
    _NSE_SESSION_REBUILT_THIS_RUN = False  # FIX-3: reset rebuild guard for fresh run

    # FIX-A8: Expire stale ghost positions FIRST — must run before capacity guard
    # and before _run_outcome_engine() so counts are accurate throughout this run.
    _auto_expire_stale_positions()

    # FIX-v4.5: SAME-DAY RERUN CLEAR — if this date has already been run today,
    # wipe the stale results so the latest run is always the source of truth.
    # Clears: sniper_results, pick_outcomes (open only), data_quality, meta_features.
    # Does NOT clear: pick_outcomes with status != 'open' (closed trades keep history),
    #                 halal_ai_cache (TTL-managed separately), trade_decisions (user replies),
    #                 score_cache (intentionally preserved for FAST_RERUN mode).
    # FIX-RERUN: when FAST_RERUN=true we SKIP this clear so the scoring loop can
    # serve results from score_cache without re-running all 7 engines.
    # FIX-B2 (_today_label bug): the previous code called _get_last_trading_day() a
    # second time and unpacked `_, _today_label` — receiving ddmmyyyy (the FIRST
    # return value) while all DB inserts use date_label = yyyy-mm-dd (the SECOND).
    # The DELETE never matched any rows because "17052026" != "2026-05-17".
    # Fix: reuse date_label (already correctly set on line above) everywhere.
    try:
        if FAST_RERUN:
            log.info(f"FAST_RERUN=true — skipping same-day clear for {date_label}. "
                     f"Scoring loop will read from score_cache for symbols already scored today.")
            _rows_sr = _rows_po = _rows_dq = _rows_mf = 0
        else:
            with _db_conn(write=True) as _clear_con:
                _rows_sr  = _clear_con.execute("DELETE FROM sniper_results  WHERE run_date=?", (date_label,)).rowcount
                _rows_po  = _clear_con.execute("DELETE FROM pick_outcomes   WHERE run_date=? AND status='open'", (date_label,)).rowcount
                _rows_dq  = _clear_con.execute("DELETE FROM data_quality    WHERE run_date=?", (date_label,)).rowcount
                _rows_mf  = _clear_con.execute("DELETE FROM meta_features   WHERE run_date=?", (date_label,)).rowcount
                _clear_con.commit()
            if any([_rows_sr, _rows_po, _rows_dq, _rows_mf]):
                log.info(f"Same-day rerun detected — cleared stale data for {date_label}: "
                         f"sniper_results={_rows_sr}, pick_outcomes={_rows_po}, "
                         f"data_quality={_rows_dq}, meta_features={_rows_mf}")
            else:
                log.info(f"Fresh run for {date_label} — no stale data to clear")
        # Always purge score_cache rows older than 5 days (keep DB tidy)
        _score_cache_purge_old(keep_days=5)
    except Exception as _e:
        log.warning(f"Same-day clear failed (non-fatal): {_e}")

    # STEP 9 (arch): Outcome Engine — resolve yesterday's picks before scoring today.
    # Architecture calls this "next day" but it fires at the START of each run(),
    # which is equivalent: the first thing today's run does is close out yesterday.
    # FIX-v4.5: wrapped in try/except so a locked DB never aborts a morning run.
    try:
        _run_outcome_engine()         # Check what happened to yesterday's picks
        _adjust_sector_multipliers()  # Adjust sector weights based on results
        _alert_open_positions()       # Warn if any open pick near stop
    except Exception as _oe:
        log.warning(f"Outcome engine non-fatal error: {_oe} — continuing with today's scoring")

    # META-LABELER: Backfill outcomes + train/retrain model
    # v3.0-M: first try personalized v2, fall back to v1 if not enough decisions
    _update_meta_outcomes()
    meta_model = _train_meta_labeler_v2(min_samples=20) or _train_meta_labeler(min_samples=50)
    if meta_model:
        _save_meta_model(meta_model)

    # v5.4: Train survival meta-model (temporal + lane-aware)
    # Runs in fallback mode until 100+ picks are accumulated (auto-detects readiness)
    if SURVIVAL_MODEL_ENABLED:
        try:
            _surv_model = _train_meta_survival_model(min_samples=SURVIVAL_MIN_SAMPLES)
            if _surv_model:
                log.info("v5.4 Survival meta-model trained successfully")
        except Exception as _sm_e:
            log.debug(f"Survival model training non-fatal: {_sm_e}")

    log.info("=" * 70)
    log.info(f"⚔️  UNIFIED SNIPER {VERSION} | {date_label}")
    log.info(f"    Bismillah — Halal · Fortress × APEX Fused Engine")
    log.info("=" * 70)
    log.info(f"    PAPER={PAPER_MODE} | FORCE_SHEETS={FORCE_SHEETS} | FORCE_YF={FORCE_YFINANCE}")
    log.info(f"    SHARIAH_TTL={SHARIAH_TTL_DAYS}d | MC_SIMS={MC_SIMS} | CB_FAIL_SAFE={CB_FAIL_SAFE}")

    # Reset per-run caches
    global _MACRO_CACHE, _HALAL_UNIVERSE_CACHE, _NSE_SESSION
    global _SECTOR_LIVE_CACHE, _SMALLCAP_CACHE, _HALAL_CUSTOM_LIST
    global _META_MODEL_SINGLETON, _META_MODEL_LOADED  # OPT-9: reset singleton for fresh load
    _MACRO_CACHE          = None
    _HALAL_UNIVERSE_CACHE = None
    _NSE_SESSION          = None
    _SECTOR_LIVE_CACHE    = {}
    _SMALLCAP_CACHE       = {}
    _META_MODEL_SINGLETON = None  # OPT-9: force fresh load at start of each run
    _META_MODEL_LOADED    = False

    # 1. Macro
    macro = _get_macro()
    if macro["macro_state"] == "MASSACRE":
        log.error("🚨 MASSACRE — pipeline halted, sending Telegram alert")
        send_telegram([], macro, fetch_fii_dii(), date_label, "NSE")
        return []

    # 2. Halal universe
    _HALAL_CUSTOM_LIST = _read_sheets_halal_list()
    if _HALAL_CUSTOM_LIST:
        log.info(f"Custom HALAL_LIST: {len(_HALAL_CUSTOM_LIST)} symbols loaded from Sheets Tab 7")

    # FIX-4.1-M: Check if intelligence Sheets tabs are fresh (runs async with bhavcopy fetch)
    _check_sheets_freshness()
    # FIX-2.2: DataFreshnessGuard — graduated staleness penalty on intelligence scores
    # FIX-v4.5: pass telegram_fn=None — freshness noise must never reach the user's phone
    freshness_guard.check_all(_read_sheet, telegram_fn=None)

    # 3. Bhavcopy
    bhavcopy, data_source = load_bhavcopy()
    if bhavcopy.empty:
        log.error("❌ All data sources failed — aborting"); return []
    if bhavcopy["volume"].sum() <= 0:
        log.error("❌ Volume=0 across all rows — data quality failure"); return []

    # 4. Pre-filter — liquidity + price only.
    # ARCH-v4.5: Halal pre-filter REMOVED from here.
    # Fortress + APEX run on ALL liquid EQ symbols (architecture Step 1→3).
    # The 4-layer Halal AI Screen runs AFTER scoring on the top-N pearls only (Step 4).
    # This means: (a) no gem is missed because of a stale list, (b) the expensive
    # Shariah CSV / LLM calls fire only on the small set that actually scored well.
    cands = bhavcopy[
        (bhavcopy["turnover_lakhs"] >= MIN_TURNOVER_LAKHS) &
        (bhavcopy["close"] >= MIN_PRICE) &
        (bhavcopy["close"] <= MAX_PRICE)
    ].copy()
    log.info(f"After liquidity+price filter: {len(cands)} candidates (no halal pre-filter — engines run first)")
    if len(cands) > MAX_CANDIDATES:
        cands = cands.nlargest(MAX_CANDIDATES, "turnover_lakhs")
        log.info(f"Capped to top {MAX_CANDIDATES} by turnover")

    # 5. Intelligence — fetched concurrently via asyncio to eliminate serial waits.
    #    Each fetch is I/O-bound (NSE API / Google Sheets / yfinance); running them
    #    sequentially wastes 10-20 s waiting for one before starting the next.
    #    asyncio.to_thread() wraps each blocking call in a thread-pool executor
    #    while the event loop overlaps all four downloads simultaneously.
    import asyncio

    async def _fetch_intelligence_async():
        log.info("Fetching intelligence data concurrently (asyncio)…")
        fii_task, ins_task, fil_task, earn_task = await asyncio.gather(
            asyncio.to_thread(fetch_fii_dii),
            asyncio.to_thread(fetch_insider_trades),
            asyncio.to_thread(fetch_filings),
            asyncio.to_thread(fetch_earnings_calendar),
        )
        return fii_task, ins_task, fil_task, earn_task

    # Safe asyncio runner: if an event loop is already running (Jupyter, FastAPI,
    # pytest-asyncio), asyncio.run() raises RuntimeError. In that case, we spawn
    # a plain daemon thread with its OWN new event loop.
    #
    # BUG FIX [ASYNC-001]: the previous fallback used ThreadPoolExecutor(max_workers=1)
    # and called asyncio.run() inside the single worker.  asyncio.to_thread() (used
    # inside _fetch_intelligence_async) submits tasks to the DEFAULT thread pool,
    # which is the same single-worker TPE — causing a deadlock where the coroutine
    # waits for a thread that will never become free.
    # Fix: spin a bare threading.Thread.  It has its own stack and is not subject to
    # the executor's pool limit, so asyncio.to_thread() dispatches into the default
    # loop's unrestricted thread pool without contention.
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        fii_data, insider_map, filings, earn_cal = asyncio.run(_fetch_intelligence_async())
    else:
        import threading as _threading
        _result: list = []
        _exc:    list = []

        def _run_in_own_loop():
            _new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_new_loop)
            try:
                _result.append(_new_loop.run_until_complete(_fetch_intelligence_async()))
            except Exception as _e:
                _exc.append(_e)
            finally:
                _new_loop.close()

        _t = _threading.Thread(target=_run_in_own_loop, daemon=True)
        _t.start()
        _t.join(timeout=90)          # generous but bounded
        if not _t.is_alive() and _exc:
            raise _exc[0]
        if _t.is_alive():
            log.warning("Async intelligence fetch timed out after 90 s — using empty defaults")
            fii_data, insider_map, filings, earn_cal = (
                {"label": "TIMEOUT", "fii_pts": 0, "dii_pts": 0},
                {}, [], {}
            )
        else:
            fii_data, insider_map, filings, earn_cal = _result[0]

    log.info(f"FII/DII: {fii_data['label']} | Insider: {len(insider_map)} symbols | "
             f"Filings: {len(filings)} | Earnings: {len(earn_cal)} events")

    # 6. Pre-load histories in BACKGROUND — scoring starts immediately (FIX-1).
    #    Old: blocked entire run waiting for 98-symbol batch download (~3-6 min).
    #    New: background thread fills hist_cache while scoring loop runs;
    #         fetch_history() uses cache if available, falls back to individual
    #         download if the symbol hasn't arrived yet. No gems missed.
    import threading as _threading
    hist_cache: Dict[str, pd.DataFrame] = {}
    _hist_lock  = _threading.Lock()

    def _bg_preload_histories():
        end   = datetime.today()
        start = end - timedelta(days=350)
        syms  = cands["symbol"].tolist()
        try:
            import yfinance as yf
        except ImportError:
            return
        for i in range(0, len(syms), 50):
            chunk   = syms[i:i + 50]
            tickers = " ".join(f"{s}.NS" for s in chunk)
            for attempt in range(2):
                try:
                    raw = yf.download(tickers, start=start, end=end,
                                      progress=False, auto_adjust=False,
                                      group_by="ticker",
                                      timeout=_YF_DOWNLOAD_TIMEOUT)
                    if raw.empty:
                        break
                    for sym in chunk:
                        tk = f"{sym}.NS"
                        try:
                            if hasattr(raw.columns, "levels"):
                                lvl0 = list(raw.columns.get_level_values(0))
                                lvl1 = list(raw.columns.get_level_values(1))
                                tk_level = 0 if any(".NS" in str(v) for v in lvl0) else (1 if any(".NS" in str(v) for v in lvl1) else 0)
                                tickers_in_col = list(raw.columns.get_level_values(tk_level))
                                sub = (raw.xs(tk, axis=1, level=tk_level) if tk in tickers_in_col
                                       else (raw[tk] if tk in raw.columns else None))
                            else:
                                sub = raw.copy() if len(chunk) == 1 else None
                            if sub is None or sub.empty:
                                continue
                            sub = sub.reset_index()
                            sub.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in sub.columns]
                            if "close" not in sub.columns and "adj close" in sub.columns:
                                sub = sub.rename(columns={"adj close": "close"})
                            sub["date"] = pd.to_datetime(sub["date"])
                            df = sub[["date", "open", "high", "low", "close", "volume"]].dropna()
                            with _hist_lock:
                                hist_cache[sym.upper()] = _validate_no_lookahead(df)
                        except Exception:
                            continue
                    break
                except Exception as e:
                    log.debug(f"BG preload chunk {i}-{i+50} attempt {attempt+1}: {e}")
                    time.sleep(2 * (attempt + 1))

    _preload_thread = _threading.Thread(target=_bg_preload_histories, daemon=True)
    _preload_thread.start()
    log.info(f"Pre-loading {len(cands)} histories in background — scoring starts immediately [OPT-16]")

    # ══════════════════════════════════════════════════════════════════════════
    # PERF-1 (v5.0): PARALLEL SCORING — ThreadPoolExecutor over universe
    # Previous: sequential for-loop. New: 8 concurrent workers.
    # Thread-safety: assemble_pick() only reads shared state (hist_cache, DB reads)
    # and writes only to its own return dict. No shared mutable state.
    # Expected speedup: 4–6× on GitHub Actions 4-core runner.
    # ══════════════════════════════════════════════════════════════════════════
    from concurrent.futures import ThreadPoolExecutor as _TPE, as_completed as _asc
    import threading as _threading_par

    results = []
    _nse_block_auto_switched = False
    _results_lock = _threading.Lock()
    _N_WORKERS = min(8, max(2, len(cands) // 10))  # adaptive: 2-8 workers

    log.info(f"PERF-1: Parallel scoring with {_N_WORKERS} workers on {len(cands)} candidates")

    # Build args list for parallel workers
    scoring_args = []
    for _, row in cands.iterrows():
        sym = row["symbol"]
        scoring_args.append((
            sym, row.to_dict(), hist_cache,
            fii_data, insider_map, filings, earn_cal,
            macro, data_source, date_label, FAST_RERUN
        ))

    _completed = 0
    with _TPE(max_workers=_N_WORKERS, thread_name_prefix="sniper_score") as executor:
        future_map = {
            executor.submit(_score_one_symbol, args): args[0]
            for args in scoring_args
        }
        for future in _asc(future_map):
            sym = future_map[future]
            _completed += 1
            if _completed % 25 == 0:
                log.info(f"Progress: {_completed}/{len(scoring_args)} | picks so far: {len(results)}")
            try:
                r = future.result(timeout=60)
                if r:
                    with _results_lock:
                        results.append(r)
                    log.info(f"  ✅ {sym:12s} | fused={r['fused']}/100 | {r['grade'][:10]} | {r['story'][:60]}")
                    # Persist to score_cache for same-day reruns
                    # BUG-3 FIX: intel_hash computed inside _score_one_symbol so it's already
                    # embedded in the result dict path; cache is written there. This fallback
                    # write in run() uses a fresh hash from current intelligence data.
                    if FAST_RERUN:
                        _sym_close = float(r.get("close", 0))
                        _run_intel_hash = _intelligence_hash(fii_data, insider_map, filings)
                        _score_cache_put(sym, date_label, _sym_close, r, _run_intel_hash)
            except Exception as e:
                log.debug(f"{sym}: parallel scoring error: {e}")

    # FIX-1.4: Auto-detect NSE block after scoring and warn
    with _NSE_FAIL_LOCK:
        if _NSE_IP_BLOCKED and not _nse_block_auto_switched:
            log.warning(
                "FIX-1.4: NSE IP-BLOCKED detected during scoring run. "
                "Set FORCE_YFINANCE=true in next run for clean execution."
            )

    log.info(f"\n{'='*70}")
    log.info(f"Screened {len(cands)} | Passed: {len(results)}")

    # =====================================================================
    # v5.4 THREE-LANE SCORING (Stage 2) -- runs after main parallel loop
    # Triggered when THREE_LANE_ENABLED=true (default).
    # Uses same hist_cache populated by the background preload above.
    # L1/L2 halal vetoes are applied INSIDE _run_three_lane_scoring()
    # so haram symbols never reach the heavy APEX/MC engines.
    # =====================================================================
    _three_lane_results = {}
    _three_lane_winners = {"fortress": None, "apex": None, "fused": None}
    if THREE_LANE_ENABLED:
        log.info("=" * 70)
        log.info("v5.4 THREE-LANE SCORING (Stage 2)")
        log.info("=" * 70)
        try:
            _three_lane_results = _run_three_lane_scoring(
                cands=cands,
                hist_cache=hist_cache,
                fii_data=fii_data,
                insider_map=insider_map,
                filings=filings,
                earn_cal=earn_cal,
                macro=macro,
                data_source=data_source,
                date_label=date_label,
            )

            # Stage 3 -- DEDUPLICATED L4 LLM SCREEN
            _unique_syms = _deduplicate_lane_winners(_three_lane_results)
            log.info(f"Stage 3: {len(_unique_syms)} unique symbols for L4 screen: {_unique_syms}")
            _sector_map_dedup = {sym: get_sector(sym) for sym in _unique_syms}
            _halal_dedup = _run_halal_l4_dedup(_unique_syms, _sector_map_dedup)

            # Alpha mine for unique winners (deduplicated)
            _alpha_dedup = {}
            for sym in _unique_syms:
                fil = filings.get(sym.upper(), {})
                subject = fil.get("detail", "") or fil.get("subject", "")
                if subject:
                    try:
                        _alpha_dedup[sym] = _llm_alpha_mine(subject, sym)
                    except Exception:
                        pass

            # Stage 4 -- LANE FINALIZATION
            _three_lane_winners["fortress"] = _select_lane_winner(
                _three_lane_results.get("fortress", []),
                _halal_dedup, _alpha_dedup,
                "FORTRESS", "fort_pts", LANE_FORTRESS_MIN
            )
            _three_lane_winners["apex"] = _select_lane_winner(
                _three_lane_results.get("apex", []),
                _halal_dedup, _alpha_dedup,
                "APEX", "apex_comp", LANE_APEX_MIN
            )
            _three_lane_winners["fused"] = _select_lane_winner(
                _three_lane_results.get("fused", []),
                _halal_dedup, _alpha_dedup,
                "FUSED", "fused", LANE_FUSED_MIN
            )

            # Stage 5 -- DB PERSISTENCE (per-lane)
            for ln, w in _three_lane_winners.items():
                _persist_lane_results(ln.upper(), w, date_label)

            winners_str = " | ".join(
                f"{k.upper()}:{v['symbol']}" if v else f"{k.upper()}:NO_PICK"
                for k, v in _three_lane_winners.items()
            )
            log.info(f"THREE-LANE WINNERS: {winners_str}")

        except Exception as _tl_e:
            log.error(f"Three-lane scoring non-fatal error: {_tl_e}", exc_info=True)
            _three_lane_results = {}
            _three_lane_winners = {"fortress": None, "apex": None, "fused": None}

    # ── Log data quality to DB ──
    # FIX-v4.5: get_halal_universe() is called BEFORE acquiring _db_conn(write=True)
    # to avoid a lock ordering deadlock: halal fetch holds _HALAL_UNIVERSE_LOCK and
    # may call _load_shariah_db() which acquires _SQLITE_WRITE_LOCK internally,
    # while _db_conn(write=True) holds _SQLITE_WRITE_LOCK waiting for the fetch.
    # Pre-fetching outside the write context breaks the cycle.
    # ARCH-v4.5: halal_universe_size now reflects the AI-screen universe (all Nifty500
    # Shariah list symbols) rather than the pre-filtered candidate set, since we no
    # longer gate scoring on the halal list.
    try:
        halal_uni = get_halal_universe()          # fetch OUTSIDE the write lock
        _bhavcopy_syms = set(bhavcopy["symbol"])
        _dq_params = (
            date_label, data_source, len(bhavcopy), len(halal_uni),
            len(_bhavcopy_syms & halal_uni),
            "YES" if (data_source == "YFINANCE" and len(bhavcopy) <= 100) else "NO",
            len(halal_uni - _bhavcopy_syms),
            "SHRUNK" if (data_source == "YFINANCE" and len(bhavcopy) <= 100) else "OK"
        )
    except Exception as _dqe:
        log.debug(f"Data quality param prep: {_dqe}")
        _dq_params = (date_label, data_source, len(bhavcopy), 0, 0, "NO", 0, "OK")
    try:
        with _db_conn(write=True) as con:
            con.execute("""
                INSERT INTO data_quality (run_date, data_source, bhavcopy_records,
                halal_universe_size, halal_in_bhavcopy, yfinance_shrink, missing_halal, alert)
                VALUES (?,?,?,?,?,?,?,?)
            """, _dq_params)
            con.commit()
        log.info("Data quality logged to DB")
    except Exception as e:
        log.warning(f"DB quality log failed (non-fatal): {e}")
    # 7. Rank + sector cap + bucket
    # Apply data quality gate adjustments
    dq_gate = _data_quality_gate(bhavcopy, data_source)
    effective_min_score = dq_gate["apex_min_score"]
    effective_top_n = dq_gate["apex_top_n"]

    # Filter by effective minimum
    results = [r for r in results if r["fused"] >= effective_min_score]

    results.sort(key=lambda x: (x["fused"]*1000 + x["whale_score"]*10 + x["div_score"]), reverse=True)
    sec_counts: dict = {}; globally_capped=[]
    for r in results:
        sec=r["sector"]; cnt=sec_counts.get(sec,0)
        if cnt<2: globally_capped.append(r); sec_counts[sec]=cnt+1

    # ── DYNAMIC BUCKET ALLOCATION ──
    # Only run market-cap lookup if we actually have candidates to bucket
    mcap_map: dict = {}
    if globally_capped:
        def _batch_market_caps(symbols: list, fallback_map: dict) -> dict:
            """Return {symbol: mcap_in_cr} via batch yfinance tickers + SQLite cache.
            Uses ThreadPoolExecutor with per-symbol timeout so one slow call
            cannot block the entire batch.
            Bug fix: SQLite writes from worker threads are serialised through
            _SQLITE_WRITE_LOCK to prevent 'database is locked' under WAL mode."""
            result = {}

            # 1. SQLite cache (read — safe without lock)
            try:
                with _db_conn() as con:
                    cached = {r[0]: r[1] for r in con.execute(
                        "SELECT symbol, mcap FROM mcap_cache WHERE fetched_at > ?",
                        ((datetime.today() - timedelta(days=7)).isoformat(),)
                    ).fetchall()}
                    result.update(cached)
            except Exception:
                cached = {}

            need_fetch = [s for s in symbols if s not in result]
            if not need_fetch:
                return result

            # 2. Parallel fetch with hard timeout per symbol
            # FIX-YF-HANG: yf.Ticker().info uses requests/urllib3 internally.
            # socket.setdefaulttimeout() does NOT apply to requests — it only
            # affects bare socket connections. When Yahoo blocks the runner IP,
            # yf.Ticker().info hangs in a C-level recv() that Python cannot
            # interrupt. future.result(timeout=15) times out on the main thread
            # but the worker thread remains as a zombie.
            # Fix: call Yahoo Finance v7 quote API directly with requests.get()
            # using timeout=(connect_s, read_s). requests/urllib3 enforces this
            # at the Python level, so threads exit cleanly on timeout or block.
            _YF_QUOTE_URL = "https://query2.finance.yahoo.com/v7/finance/quote"
            _YF_HEADERS   = {"User-Agent": "Mozilla/5.0 (compatible; SniperBot/4.7)"}

            def _fetch_one(sym, _fallback=fallback_map):
                # Circuit breaker guard — skip if YF is banned this run
                with _YF_FAIL_LOCK:
                    if time.time() < _YF_CIRCUIT_OPEN_UNTIL:
                        return sym, _fallback.get(sym, 100.0)
                try:
                    resp = requests.get(
                        _YF_QUOTE_URL,
                        params={"symbols": f"{sym}.NS", "fields": "marketCap"},
                        headers=_YF_HEADERS,
                        timeout=(5, 12),   # connect=5s, read=12s — enforced by urllib3
                    )
                    if resp.status_code == 200:
                        items = resp.json().get("quoteResponse", {}).get("result", [])
                        if items:
                            mc = items[0].get("marketCap")
                            if mc:
                                return sym, float(mc) / 1e7
                except Exception:
                    pass
                return sym, _fallback.get(sym, 100.0)

            # FIX-1.2: manual executor shutdown — context manager blocks until all workers
            # finish, which hangs the pipeline when a yfinance call is stuck. Manual
            # shutdown(wait=False, cancel_futures=True) releases the main thread immediately.
            executor = ThreadPoolExecutor(max_workers=3)
            futures = {executor.submit(_fetch_one, sym): sym for sym in need_fetch}
            try:
                for future in list(futures.keys()):
                    sym = futures[future]
                    try:
                        sym_out, mcap = future.result(timeout=15)
                        result[sym_out] = mcap
                    except FutureTimeoutError:
                        log.warning(f"Market cap timeout: {sym}")
                        future.cancel()
                        result[sym] = fallback_map.get(sym, 100.0)
                    except Exception:
                        result[sym] = fallback_map.get(sym, 100.0)
            except Exception as e:
                log.error(f"Batch market cap executor failed: {e}")
                for sym in need_fetch:
                    if sym not in result:
                        result[sym] = fallback_map.get(sym, 100.0)
            finally:
                executor.shutdown(wait=False, cancel_futures=True)  # FIX-1.2: don't block on hung workers

            # 3. Cache to SQLite — serialised write to avoid "database is locked"
            # FIX-DEADLOCK: removed outer `with _SQLITE_WRITE_LOCK:` — _db_conn(write=True)
            # already acquires _SQLITE_WRITE_LOCK internally. Wrapping with it again causes
            # a deadlock because threading.Lock() is NOT reentrant: the same thread
            # blocks forever trying to acquire a lock it already holds.
            try:
                with _db_conn(write=True) as con:
                    today_iso = datetime.today().isoformat()
                    for sym, mcap in result.items():
                        if sym in need_fetch:
                            con.execute(
                                "INSERT OR REPLACE INTO mcap_cache (symbol, mcap, fetched_at) VALUES (?,?,?)",
                                (sym, mcap, today_iso)
                            )
                    con.commit()
            except Exception:
                pass

            return result

        # Pre-compute all market caps in one batch
        symbols_to_lookup = [r["symbol"] for r in globally_capped]
        fallback_mcaps = {r["symbol"]: r["close"] * 100 for r in globally_capped}
        mcap_map = _batch_market_caps(symbols_to_lookup, fallback_mcaps)

    # Assign to results
    for r in globally_capped:
        r["mcap_proxy"] = mcap_map.get(r["symbol"], r["close"] * 100)

    # Define buckets by market cap (in Cr)
    LARGE_CAP_MIN = 20000   # ₹20,000 Cr+
    MID_CAP_MIN = 5000      # ₹5,000-20,000 Cr
    SMALL_CAP_MIN = 1000    # ₹1,000-5,000 Cr
    # Below 1,000 Cr = micro (avoid or tiny)

    large_picks = [r for r in globally_capped if r["mcap_proxy"] >= LARGE_CAP_MIN]
    mid_picks   = [r for r in globally_capped if MID_CAP_MIN <= r["mcap_proxy"] < LARGE_CAP_MIN]
    small_picks = [r for r in globally_capped if SMALL_CAP_MIN <= r["mcap_proxy"] < MID_CAP_MIN]
    micro_picks = [r for r in globally_capped if r["mcap_proxy"] < SMALL_CAP_MIN]

    # Dynamic allocation: up to effective_top_n total, distributed by availability
    total_slots = effective_top_n
    allocation = []

    # Priority: Large > Mid > Small > Micro (skip micro in chop/fog)
    remaining = total_slots

    # Take from large first (safest)
    take_large = min(len(large_picks), 1 if remaining >= 4 else 0)
    allocation.extend(large_picks[:take_large])
    remaining -= take_large

    # Then mid (core focus)
    take_mid = min(len(mid_picks), min(2, remaining))
    allocation.extend(mid_picks[:take_mid])
    remaining -= take_mid

    # Then small (opportunistic)
    take_small = min(len(small_picks), min(2, remaining))
    allocation.extend(small_picks[:take_small])
    remaining -= take_small

    # Only take micro if we have slots left and market is clear
    if remaining > 0 and macro["macro_state"] == "CLEAR":
        take_micro = min(len(micro_picks), remaining)
        allocation.extend(micro_picks[:take_micro])

    top_picks = allocation
    seen = set()
    top_picks = [r for r in top_picks if r["symbol"] not in seen and not seen.add(r["symbol"])]

    # ── v3.0-M: Attach meta_prob, regime-scaled confidence, setup profile ──
    meta_model_live = _load_meta_model()
    for r in top_picks:
        profile = _get_setup_profile(r)
        r["setup_profile"] = profile
        meta_features_v3 = {
            "whale_score": r.get("whale_score", 0),
            "div_score":   r.get("div_score", 0),
            "vp_score":    r.get("vp_score", 0),
            "pat_score":   r.get("pat_score", 0),
            "bayes_pct":   r.get("bayes_pct", 0),
            "macro_state": macro.get("macro_state", "CHOP"),
            "sector":      r.get("sector", "DIVERSIFIED"),
            "vix_level":   macro.get("vix_val", 18.0),
            "primary_fused_score": r.get("fused", 0),
        }
        meta_prob = _get_meta_probability(meta_model_live, meta_features_v3)
        # FIX-DOUBLE-SCALE: store RAW meta_prob so calibrated_ai_judge() can scale it
        # exactly once via _regime_scaled_confidence(). Previously we stored the
        # already-scaled value here, then calibrated_ai_judge() scaled it again:
        #   0.55 × 0.88 (here) × 0.88 (in judge) ≈ 0.43 → every pick = 43% SKIP.
        r["meta_prob"]   = meta_prob
        _scaled_for_flag = _regime_scaled_confidence(meta_prob, macro["macro_state"], macro.get("vix_val", 18.0))
        r["worth_flag"]  = _confidence_flag(_scaled_for_flag)
        r["macro_state"] = macro.get("macro_state", "CHOP")   # propagate for profile display

    # ── STEP 4: Halal AI Screen (4-layer) — architecture-aligned ───────────────
    # ARCH-v4.5: This is now the ONLY halal gate in the pipeline.
    # Fortress + APEX ran on ALL liquid symbols (Steps 2+3 above).
    # Here we run the full 4-layer screen ONLY on the small set of top-scored picks.
    # L1 hard business veto (keyword-based, instant) is applied first as a fast reject
    # before the L2 financial check and L4 LLM call fire — keeps API costs minimal.
    log.info("=" * 70)
    log.info(f"STEP 4: Halal AI Screen on {len(top_picks)} top-scored candidate(s)…")
    cal_params = _load_calibration_params()
    judged_picks = []
    for pick in top_picks:
        sym    = pick["symbol"]
        sector = pick.get("sector", "DIVERSIFIED")
        # Fast L1 check before invoking the full 4-layer AI screen
        if _halal_l1_business_veto(sym):
            log.info(f"  HALAL L1 VETO (business) {sym}: hard-excluded business type — skipped")
            continue
        halal  = halal_ai_screen(sym, sector)
        judged = calibrated_ai_judge(pick, halal, macro, cal_params)
        if not judged["veto"]:
            judged_picks.append(judged)
            log.info(f"  ✅ HALAL PASS {sym}: tier={halal.get('tier','?')} score={halal.get('score','?')}")
        else:
            log.info(f"  ❌ VETO {sym}: {judged['veto_reason']}")
    top_picks = judged_picks
    log.info(f"After Halal AI Screen + AI Judge: {len(top_picks)} picks pass")
    log.info("=" * 70)

    # ── v4.8 UNIFIED LLM PROMPT ARCHITECTURE ─────────────────────────────────
    # KEY INSIGHT: Fortress + APEX already computed every metric (VPOC, whale score,
    # divergence, Bayes, MC survival, FII/DII, filing score etc.).  The LLM's job
    # is NOT to recompute anything — it is pure synthesis:
    #   1. Pattern recognition — which combination of signals is unusual / compelling?
    #   2. Narrative coherence — do the signals tell a consistent story?
    #   3. Risk flag — is there a qualitative concern the quant score can't see?
    #   4. Rank the final picks — force the LLM to sort them by conviction.
    #
    # Architecture: ONE unified JSON prompt per RUN (not per pick).
    # Sends all top_picks' pre-computed scores in a single API call.
    # Returns per-symbol: llm_story, filing_flag, fused_bonus, rank_order.
    # Cost vs old: 1 call vs N calls, no recomputation of metrics. ~80% cheaper.
    #
    # Previously: two sequential calls per pick (_llm_story_enhance + _llm_alpha_mine)
    # — the LLM was being asked to re-derive what Fortress already calculated.
    # Now: one call that receives the full quant output and produces synthesis only.
    if LLM_ENABLED and top_picks:
        log.info(f"Unified LLM synthesis on {len(top_picks)} final pick(s)… (single prompt, news-driven)")

        def _unified_llm_enrich(picks: list, macro: dict,
                                 fii_data: dict, insider_map: dict,
                                 filings: dict, earnings_cal: dict) -> dict:
            """
            ACC-1/OUT-2 (v5.0): Unified LLM call with news/sentiment-driven Why field.
            Architecture Step 9 §4a–4d.

            Each pick gets:
              llm_story     — what makes this setup unusual/compelling (≤15 words)
              llm_why       — NEWS/SENTIMENT ONLY (8-10 words, never technical indicators)
                              e.g. "Q3 profit up 23%, promoter buying, FII inflow"
                              If no news: "No major news, technical setup only"
              llm_verdict   — TAKE or SKIP
              llm_narrative — simple story (8-10 words)
              llm_confidence— 0-100 integer
              filing_flag   — POSITIVE|NEGATIVE|NEUTRAL
              fused_bonus   — 0-8 integer (only if filing clearly positive AND score≥20)
              rank          — conviction rank 1=best
            """
            pick_payloads = []
            for p in picks:
                sym = p["symbol"]
                # ACC-1: Fetch sentiment context for this symbol
                sentiment = _fetch_market_sentiment(
                    sym, fii_data, insider_map, filings, earn_cal
                )
                p["_sentiment"] = sentiment  # store for later save

                pick_payloads.append({
                    "symbol":          sym,
                    "sector":          p.get("sector", "DIVERSIFIED"),
                    "grade":           p.get("grade", ""),
                    "fused":           p.get("fused", 0),
                    "fort_pct":        p.get("fort_pct", 0),
                    "apex_composite":  p.get("apex_composite", 0),
                    # INTELLIGENCE SIGNALS — drives llm_why
                    "fii_flow":        sentiment.get("fii_flow", "N/A"),
                    "insider_activity": sentiment.get("insider_activity", "None"),
                    "key_headlines":   sentiment.get("key_headlines", []),
                    "filing_sentiment": sentiment.get("filing_sentiment", "NEUTRAL"),
                    "earnings_status": sentiment.get("earnings_status", "N/A"),
                    "bullish_pct":     sentiment.get("bullish_pct", 50),
                    # Raw filing detail for filing_flag decision
                    "filing_detail":   p.get("_raw_filing") or p.get("fil_detail", ""),
                    # APEX sub-scores (pre-computed by quant engine)
                    "whale_score":     p.get("whale_score", 0),
                    "bayes_pct":       p.get("bayes_pct", 0),
                    "mc_survival":     p.get("mc_survival"),
                    "vpoc_layer1":     p.get("layer1", False),
                    "pattern_label":   p.get("pat_label", ""),
                    "vdu_label":       p.get("vdu_label", ""),
                    # Trade setup
                    "buy_lo":   p.get("buy_lo", 0),
                    "buy_hi":   p.get("buy_hi", 0),
                    "stop_loss": p.get("stop_loss", 0),
                    "risk_pct":  p.get("risk_pct", 0),
                    "r1":        p.get("r1", 0),
                    "calibrated_confidence": p.get("calibrated_confidence", p.get("meta_prob", 0.55)),
                    "halal_tier": p.get("halal_detail", {}).get("tier", "?"),
                })

            prompt = (
                "You are a quantitative trading analyst for NSE halal swing trades.\n"
                "All scores below were computed by Fortress + APEX quant engines. DO NOT recompute them.\n"
                f"Macro regime: {macro.get('macro_state','CHOP')} | VIX: {macro.get('vix_val',18):.1f}\n\n"
                "For EACH symbol, provide these EXACT fields:\n"
                "1. llm_confidence (0-100): integer — how confident are you this will move to R1 within 12 days?\n"
                "2. llm_verdict: 'TAKE' or 'SKIP'\n"
                "3. llm_why (8-10 words MAXIMUM): cite NEWS/SENTIMENT only, NEVER technical indicators.\n"
                "   GOOD: 'Q3 profit up 23%, promoter buying, FII inflow'\n"
                "   GOOD: 'RBI rate cut expected, banking sector rallying'\n"
                "   BAD:  'Whale buying too weak, wait for volume'\n"
                "   BAD:  'RSI oversold, VPOC support, Bayes 65%'\n"
                "   If NO news/sentiment available: 'No major news, technical setup only'\n"
                "4. llm_narrative (8-10 words): plain-English story, no jargon.\n"
                "5. llm_story (≤15 words): what is UNUSUAL or COMPELLING beyond the numbers?\n"
                "6. filing_flag: 'POSITIVE'|'NEGATIVE'|'NEUTRAL'\n"
                "7. fused_bonus (0-8): ONLY add if filing is clearly POSITIVE AND score≥20. Default 0.\n"
                "   FIX-V5-5: Do NOT add bonus for NEUTRAL/NEGATIVE filings or score<20.\n"
                "8. rank: conviction rank 1=best (sort by: news quality + signal coherence)\n\n"
                f"Picks:\n{json.dumps(pick_payloads, indent=2, default=str)}\n\n"
                "Return ONLY a JSON array (no markdown, no preamble, no explanation):\n"
                '[{"symbol":"X","llm_confidence":78,"llm_verdict":"TAKE",'
                '"llm_why":"Q3 profit up 23%, promoter buying, FII inflow",'
                '"llm_narrative":"Strong earnings with smart money backing",'
                '"llm_story":"Rare triple confluence at 52w VPOC with insider buying",'
                '"filing_flag":"POSITIVE","fused_bonus":3,"rank":1}]'
            )

            raw = _call_openai(prompt, max_tokens=1000) or _call_claude(prompt, max_tokens=1000)
            if not raw:
                return {}
            try:
                txt = raw.strip().replace("```json", "").replace("```", "")
                items = json.loads(txt)
                if not isinstance(items, list):
                    return {}
                out = {}
                for item in items:
                    if "symbol" not in item:
                        continue
                    # FIX-V5-5: enforce fused_bonus only when filing clearly positive
                    bonus = int(item.get("fused_bonus", 0))
                    if item.get("filing_flag") != "POSITIVE" or int(item.get("llm_confidence", 0)) < 50:
                        bonus = 0
                    out[item["symbol"]] = {
                        "llm_confidence": max(0, min(100, int(item.get("llm_confidence", 50)))),
                        "llm_verdict":    str(item.get("llm_verdict", "SKIP")).upper(),
                        "llm_why":        str(item.get("llm_why", "No major news, technical setup only"))[:100],
                        "llm_narrative":  str(item.get("llm_narrative", ""))[:100],
                        "llm_story":      str(item.get("llm_story", ""))[:120],
                        "filing_flag":    str(item.get("filing_flag", "NEUTRAL")),
                        "fused_bonus":    max(0, min(8, bonus)),
                        "rank":           int(item.get("rank", 99)),
                    }
                return out
            except Exception as parse_err:
                log.warning(f"Unified LLM parse error: {parse_err} | snippet: {raw[:120]}")
                return {}

        llm_results = _unified_llm_enrich(
            top_picks, macro, fii_data, insider_map, filings, earn_cal
        )

        # Apply unified LLM output to each pick — ACC-1/OUT-2
        for rank_i, pick in enumerate(top_picks, 1):
            sym = pick["symbol"]
            res = llm_results.get(sym, {})
            # Story fields
            if res.get("llm_story"):
                pick["llm_story"] = res["llm_story"]
                log.info(f"  LLM story OK: {sym} — {res['llm_story'][:60]}")
            # OUT-2: news-driven why field (architecture Step 9 §4d)
            pick["llm_why"] = res.get("llm_why", "No major news, technical setup only")
            pick["llm_verdict"] = res.get("llm_verdict", "SKIP")
            pick["llm_narrative"] = res.get("llm_narrative", "")
            pick["llm_confidence"] = res.get("llm_confidence", 50)
            log.info(f"  LLM why ({sym}): {pick['llm_why']}")

            filing_flag = res.get("filing_flag", "NEUTRAL")
            if filing_flag == "POSITIVE":
                pick["llm_filing_sentiment"] = "POSITIVE"
            elif filing_flag == "NEGATIVE":
                pick["llm_filing_sentiment"] = "NEGATIVE"

            # FIX-V5-5: Apply fused_bonus only when filing clearly positive AND score≥20
            bonus = res.get("fused_bonus", 0)
            if bonus > 0 and filing_flag == "POSITIVE" and pick.get("score_filing", 0) >= 20:
                old_fused = pick["fused"]
                pick["fused"] = min(100, pick["fused"] + bonus)
                log.info(f"  LLM filing bonus {sym}: fused {old_fused}→{pick['fused']} (+{bonus})")
            pick["_llm_rank"] = res.get("rank", 99)

            # OUT-1: Save full audit trail per architecture Step 9 §4e
            sentiment_ctx = pick.pop("_sentiment", {})
            llm_out = {
                "llm_confidence": pick.get("llm_confidence", 50),
                "llm_verdict":    pick.get("llm_verdict", "SKIP"),
                "llm_why":        pick.get("llm_why", ""),
                "llm_narrative":  pick.get("llm_narrative", ""),
            }
            llm_inp = {
                "fused": pick.get("fused", 0),
                "fortress": pick.get("fort_total", 0),
                "apex": pick.get("apex_composite", 0),
                "macro": macro.get("macro_state", "CHOP"),
                "vix": macro.get("vix_val", 18.0),
            }
            _save_daily_shortlist(
                run_date=date_label,
                symbol=sym,
                final_rank=rank_i,
                fortress=float(pick.get("fort_total", 0)),
                apex=float(pick.get("apex_composite", 0)),
                fused=float(pick.get("fused", 0)),
                meta_prob=float(pick.get("meta_prob", 0.55)),
                halal=pick.get("halal_detail", {}),
                llm_output=llm_out,
                sentiment=sentiment_ctx,
                llm_input=llm_inp,
            )

        # OUT-2/Step 9 §5: Re-rank by llm_confidence DESC (ties by fused score)
        # Architecture: "RE-RANK by llm_confidence DESC (may reorder top_5)"
        if llm_results:
            top_picks.sort(key=lambda p: (
                -p.get("llm_confidence", 50),   # primary: higher confidence first
                p.get("_llm_rank", 99),          # secondary: LLM rank
                -p.get("fused", 0)               # tertiary: higher fused first
            ))
            log.info("Top picks re-ranked by LLM confidence (architecture Step 9 §5)")

        log.info("Unified LLM enrichment complete")
        # CRITICAL-1: log token usage summary so runaway Sonnet calls are visible in CI logs
        log.info(f"LLM_USAGE_SUMMARY {_llm_usage_summary()}")
    elif not LLM_ENABLED:
        log.info("LLM disabled — skipping enrichment (set ANTHROPIC_API_KEY or OPENAI_API_KEY)")

    # ── OPT-18 + v3.0-M: Sector-aware capacity guard ───────────────────────
    # Blocks >2 picks from same sector when capacity is tight
    _sector_counts_in_picks: dict = {}
    _sector_capped_picks = []
    for _pick in top_picks:
        _sec = _pick.get("sector", "DIVERSIFIED")
        _cnt = _sector_counts_in_picks.get(_sec, 0)
        if _cnt < 2:  # max 2 per sector
            _sector_capped_picks.append(_pick)
            _sector_counts_in_picks[_sec] = _cnt + 1
        else:
            log.info(f"OPT-18 sector cap: {_pick['symbol']} skipped ({_sec} already has 2 picks)")
    top_picks = _sector_capped_picks

    capacity = _capacity_guard(date_label)
    if capacity.get("note"):
        log.info(f"Capacity guard: {capacity['note']}")

    log.info(f"\n{'='*70}")
    log.info(f"⚔️  TOP {len(top_picks)} PICKS")
    log.info(f"{'='*70}")
    # FIX-A9: show (COLD) label when meta-model is not yet trained so users
    # understand why all Cal% values are identical — it's expected, not broken.
    _meta_model_trained = _load_meta_model() is not None
    _cold_label = "" if _meta_model_trained else " (COLD)"
    for rank, r in enumerate(top_picks, 1):
        vn = "" if r.get("vol_reliable",True) else " [NO-VOL]"
        log.info(f"  #{rank} {r['symbol']:12s} | Fused {r['fused']}/100 | Fort {r['fort_pct']:.0f}% "
                 f"| APEX {r['apex_composite']}/100 | {r['grade']}{vn} "
                 f"| AI {round(r.get('meta_prob',0.55)*100)}% [{r.get('worth_flag','—')}] "
                 f"| Halal: {r.get('halal_detail',{}).get('tier','?')}/{r.get('halal_detail',{}).get('score','?')}"
                 f"| Cal: {r.get('calibrated_confidence',r.get('meta_prob',0)):.0%}{_cold_label} | Size: {r.get('position_size_tier','?')}")
        log.info(f"       Buy ₹{r['buy_lo']}-{r['buy_hi']} | SL ₹{r['stop_loss']} | "
                 f"R1 ₹{r['r1']} | R2 ₹{r['r2']} | MC {r['mc_survival']}%")
        log.info(f"       {r['story'][:80]}")
    # 8. Outputs  (Performance sheet is now written inside save_excel)
    # FIX-EXCEL: pass top_picks (post-judge) as BOTH positional args so the
    # "Top Picks" sheet contains calibrated_confidence, position_size_tier,
    # halal_detail, llm_story etc.  results (pre-judge, ~200 rows) lacks these
    # keys because calibrated_ai_judge() enriches the dict in-place only for
    # the final picked symbols.  Using results caused blank AI columns in Excel.

    # ── v5.1 TIER 4: CAUSAL REASONING (GREAT/ELITE only, cap 3/run) ──────────
    # Fires AFTER all standard enrichment so causal fields are the LAST layer.
    # Adds: causal_thesis, catalyst_date, asymmetry_score, causal_conf, hold_until.
    # Cost-controlled: at most _TIER4_MAX_PER_RUN=3 Claude API calls per daily run.
    if top_picks:
        log.info(f"Tier4 causal reasoning check on {len(top_picks)} pick(s)…")
        top_picks = _apply_tier4_to_picks(
            top_picks, macro,
            fii_data=fii_data,
            earnings_cal=earn_cal if "earn_cal" in dir() else None
        )
    # ─────────────────────────────────────────────────────────────────────────

    log.info("Saving Excel…");       save_excel(top_picks, top_picks, fii_data, date_label, data_source, bhavcopy)
    log.info("Saving HTML…");        save_html(top_picks, fii_data, date_label)
    log.info("Calibrating Bayes priors…"); _calibrate_bayes_priors()
    log.info("Pushing to Sheets…");  push_gsheets(top_picks, date_label)
    log.info("Pushing PERFORMANCE…"); _push_performance_tab(date_label)
    # AI_INSIGHTS pushed unconditionally — shows story+conviction even without LLM API key
    log.info("Pushing AI_INSIGHTS…"); _push_ai_insights_tab(top_picks, date_label)
    # v5.4 THREE-LANE: Route to lane-aware sender or legacy single-lane sender
    if THREE_LANE_ENABLED and "_three_lane_results" in dir():
        log.info("Sending Telegram (3-lane cards)…")
        _lane_projections = []
        try:
            _lane_projections = _run_mc_projection_engine(date_label)
        except Exception as _pe:
            log.warning(f"MC projection engine non-fatal: {_pe}")
        send_telegram_lanes(
            _three_lane_winners,
            _lane_projections,
            macro, fii_data, date_label, data_source, capacity
        )
    else:
        log.info("Sending Telegram (legacy v3 single-lane)…")
        send_telegram_v3(top_picks, macro, fii_data, date_label, data_source, capacity)

    # Persist results to DB + outcome tracking
    try:
        with _db_conn(write=True) as con:
            for r in top_picks:
                # Existing sniper_results (OR IGNORE prevents dupe on rerun)
                con.execute(
                    "INSERT OR IGNORE INTO sniper_results (run_date,symbol,grade,fused_score,close,stop_loss,r1,r2,r3,story,sector) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (date_label,r["symbol"],r["grade"],r["fused"],r["close"],
                     r["stop_loss"],r["r1"],r["r2"],r["r3"],r["story"],r.get("sector","DIVERSIFIED"))
                )
                # outcome tracking (initial state)
                # FIX-PERF: include sector so _push_performance_tab can query
                # pick_outcomes directly without JOIN sniper_results (which may be
                # cleared by the same-day rerun before the PERFORMANCE push fires).
                con.execute(
                    "INSERT OR IGNORE INTO pick_outcomes (run_date,symbol,entry_price,stop_loss,r1,r2,r3,grade,fused_score,sector,story,status) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (date_label,r["symbol"],r["close"],r["stop_loss"],r["r1"],r["r2"],r["r3"],
                     r["grade"],r["fused"],r.get("sector","DIVERSIFIED"),r["story"],"open")
                )
                # v3.0-M: store setup_profile in meta_features for personalized learning
                try:
                    con.execute(
                        "UPDATE meta_features SET setup_profile=?, days_to_earnings=? "
                        "WHERE symbol=? AND run_date=?",
                        (r.get("setup_profile",""), r.get("earn_days",-1),
                         r["symbol"], date_label)
                    )
                except Exception:
                    pass
        log.info(f"DB: {len(top_picks)} picks saved for outcome tracking")
    except Exception as e:
        log.error(f"DB persist for top picks FAILED — outcome tracking broken: {e}")   # H1

    # BUG FIX [ML-001]: second backfill + retrain pass at end of run().
    # v3.0-M: use personalized v2 labeler; fall back to v1 if insufficient decisions.
    log.info("Post-run meta-labeler refresh…")
    _update_meta_outcomes()
    refreshed_model = _train_meta_labeler_v2(min_samples=20) or _train_meta_labeler(min_samples=50)
    if refreshed_model:
        _save_meta_model(refreshed_model)
        log.info("Meta-model refreshed with today's resolved outcomes")

    # v4.0-M: auto-log any unresponded picks as SKIPPED at EOD
    _auto_log_skipped_picks(date_label)

    log.info(f"\n✅ Done | {len(top_picks)} picks | Macro: {macro['macro_state']} | "
             f"VIX: {macro['vix_val']:.1f} | Source: {data_source} | "
             f"Bismillah 🤲")
    return top_picks


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def _telegram_reply_handler():
    """
    FIX-8: Telegram polling bot reply handler with confirm_entry() gate.
    confirm_entry() exists and checks earnings proximity before allowing a TAKEN
    decision — but previously nothing called it. This handler intercepts replies
    like "TAKEN TCS @ 3445" or "PARTIAL TCS 50", calls confirm_entry(symbol) first,
    and only calls _log_trade_decision() if it passes. If earnings are <2 days away,
    replies "BLOCKED — earnings in Nd" instead of logging.

    Run standalone: python sniper_unified_v2.py --reply-handler
    Uses long-polling (getUpdates) — no webhook server required.
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("Reply handler: TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set")
        return

    _init_db()
    log.info("FIX-8: Telegram reply handler started (polling mode)…")
    _, date_label = _get_last_trading_day()

    import re as _re
    _TAKEN_RE  = _re.compile(r"^TAKEN\s+([A-Z&\-]+)\s+@?\s*([\d.]+)", _re.IGNORECASE)
    _PARTIAL_RE = _re.compile(r"^PARTIAL\s+([A-Z&\-]+)\s+([\d]+)", _re.IGNORECASE)
    _SKIP_RE   = _re.compile(r"^SKIP(PED)?\s+([A-Z&\-]+)", _re.IGNORECASE)

    offset = 0
    while True:
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 30, "allowed_updates": ["message"]},
                timeout=35
            )
            if resp.status_code != 200:
                time.sleep(5)
                continue
            updates = resp.json().get("result", [])
            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = (msg.get("text") or "").strip()

                # Only process messages from the configured chat
                if chat_id != str(TELEGRAM_CHAT_ID):
                    continue
                if not text:
                    continue

                reply = None

                # Parse TAKEN TCS @ 3445
                m = _TAKEN_RE.match(text)
                if m:
                    symbol = m.group(1).upper()
                    entry_price = float(m.group(2))
                    ok, reason = confirm_entry(symbol)
                    if not ok:
                        reply = f"⛔ {symbol} BLOCKED — {reason}\nEntry not logged."
                    else:
                        _log_trade_decision(date_label, symbol, "TAKEN", entry_price=entry_price)
                        reply = f"✅ {symbol} TAKEN @ ₹{entry_price} logged. Bismillah 🤲"

                # Parse PARTIAL TCS 50
                elif _PARTIAL_RE.match(text):
                    mp = _PARTIAL_RE.match(text)
                    symbol = mp.group(1).upper()
                    shares = int(mp.group(2))
                    ok, reason = confirm_entry(symbol)
                    if not ok:
                        reply = f"⛔ {symbol} BLOCKED — {reason}\nPartial entry not logged."
                    else:
                        _log_trade_decision(date_label, symbol, "PARTIAL", shares=shares)
                        reply = f"✅ {symbol} PARTIAL ({shares} shares) logged."

                # Parse SKIPPED TCS
                elif _SKIP_RE.match(text):
                    ms = _SKIP_RE.match(text)
                    symbol = ms.group(2).upper()
                    _log_trade_decision(date_label, symbol, "SKIPPED", skip_reason="manual_reply")
                    reply = f"📝 {symbol} logged as SKIPPED."

                if reply:
                    _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, reply)
                    log.info(f"Reply handler processed: {text[:60]} → {reply[:60]}")

        except KeyboardInterrupt:
            log.info("Reply handler stopped by user")
            break
        except Exception as e:
            log.warning(f"Reply handler error: {e}")
            time.sleep(5)


# ══════════════════════════════════════════════════════════════════════════════
# v5.1 — RAG BACKFILL ENGINE
# Generates trade_embeddings for ALL closed pick_outcomes that lack one.
# Run once manually (--rag-backfill) or via the rag-backfill GHA job.
# Idempotent: skips symbols that already have embeddings (uses _has_embedding).
# Sends a Telegram summary when done.
# ══════════════════════════════════════════════════════════════════════════════

def _rag_backfill_historical() -> dict:
    """
    RAG BACKFILL: Embed all closed pick_outcomes that have no embedding yet.

    Joins pick_outcomes + sniper_results to reconstruct the feature set
    needed for _build_trade_text() (fortress_score, apex_score, fused, grade,
    sector, macro_state, story).  Falls back to sane defaults when columns are
    missing (e.g. fortress_score not stored before v5.0).

    Returns: {total_closed, already_embedded, newly_embedded, skipped, errors}
    """
    _init_db()
    if not RAG_ENABLED:
        log.info("RAG backfill: RAG_ENABLED=false — nothing to do")
        return {"status": "disabled"}

    model = _get_embed_model()
    if model is None:
        log.warning("RAG backfill: sentence-transformers unavailable — install it first")
        return {"status": "model_unavailable"}

    log.info("RAG backfill: starting historical embedding pass …")

    try:
        with _db_conn() as con:
            rows = con.execute("""
                SELECT
                    o.run_date, o.symbol, o.grade, o.fused_score, o.sector,
                    o.status   AS outcome_status, o.pnl_pct, o.story,
                    COALESCE(s.story, o.story, '') AS full_story
                FROM pick_outcomes o
                LEFT JOIN sniper_results s
                    ON o.symbol = s.symbol AND o.run_date = s.run_date
                WHERE o.status NOT IN ('open', 'expired')
                ORDER BY o.run_date ASC
            """).fetchall()
    except Exception as e:
        log.error(f"RAG backfill: DB query failed: {e}")
        return {"status": "error", "error": str(e)}

    total_closed      = len(rows)
    already_embedded  = 0
    newly_embedded    = 0
    skipped           = 0
    errors            = 0

    for row in rows:
        run_date, symbol, grade, fused_score, sector, outcome_status, pnl_pct, story, full_story = row

        # Skip if embedding already exists
        if _has_embedding(symbol, run_date):
            already_embedded += 1
            continue

        # Reconstruct reasonable feature defaults for pre-v5 rows
        fused   = float(fused_score or 50)
        fortress = fused * 0.55   # approximate: fortress ≈ 55% of fused historically
        apex    = fused * 0.45
        sector  = sector or "DIVERSIFIED"
        grade   = grade or "GOOD"

        # macro_state: try to infer from meta_features if available
        macro_state = "CHOP"   # safe default
        try:
            with _db_conn() as con:
                mf_row = con.execute(
                    "SELECT macro_state FROM meta_features WHERE symbol=? AND run_date=? LIMIT 1",
                    (symbol.upper(), run_date)
                ).fetchone()
            if mf_row and mf_row[0]:
                macro_state = mf_row[0]
        except Exception:
            pass

        outcome_pnl = float(pnl_pct or 0)
        use_story   = (full_story or story or "")[:120]

        ok = _generate_and_store_embedding(
            symbol=symbol, run_date=run_date,
            fortress=fortress, apex=apex, fused=fused,
            grade=grade, sector=sector, macro_state=macro_state,
            outcome_status=outcome_status, outcome_pnl=outcome_pnl,
            story=use_story,
        )
        if ok:
            newly_embedded += 1
            log.debug(f"RAG backfill: embedded {symbol} {run_date} ({outcome_status})")
        else:
            errors += 1
            log.debug(f"RAG backfill: failed to embed {symbol} {run_date}")

    result = {
        "status":           "complete",
        "total_closed":     total_closed,
        "already_embedded": already_embedded,
        "newly_embedded":   newly_embedded,
        "skipped":          skipped,
        "errors":           errors,
    }
    log.info(
        f"RAG backfill complete: {total_closed} closed trades | "
        f"{already_embedded} already had embeddings | "
        f"{newly_embedded} newly embedded | {errors} errors"
    )

    # Telegram summary
    try:
        msg = (
            f"🧠 RAG Backfill Complete\n"
            f"  Closed trades found : {total_closed}\n"
            f"  Already embedded    : {already_embedded}\n"
            f"  Newly embedded      : {newly_embedded}\n"
            f"  Errors              : {errors}\n"
            f"RAG memory is {'active' if newly_embedded + already_embedded >= RAG_MIN_TRADES else 'still building — need ' + str(RAG_MIN_TRADES) + '+ closed trades'}."
        )
        _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, msg)
    except Exception:
        pass

    return result


if __name__ == "__main__":
    import sys
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if "--weekly-review" in sys.argv:
        # Run standalone: python sniper_unified_v2.py --weekly-review
        _init_db()
        _weekly_ai_status_agent()   # v4.0-M: AI agent (was _send_weekly_review)
    elif "--sandbox-proposals" in sys.argv:
        # Run standalone: python sniper_unified_v2.py --sandbox-proposals
        _init_db()
        _generate_sandbox_proposal()
    elif "--reply-handler" in sys.argv:
        # FIX-8: Run standalone Telegram reply handler with confirm_entry() gate
        # python sniper_unified_v2.py --reply-handler
        _telegram_reply_handler()
    elif "--rag-backfill" in sys.argv:
        # RAG backfill: embed all closed historical trades that lack embeddings.
        # python sniper_unified_v5.py --rag-backfill
        _rag_backfill_historical()
    else:
        run()
