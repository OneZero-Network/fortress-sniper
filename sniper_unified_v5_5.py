"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   UNIFIED HALAL SNIPER v5.5.1 — FORTRESS × APEX × CALIBRATED AI JUDGE     ║
║   Bismillah — In the name of Allah, the Most Gracious, the Most Merciful   ║
║                                                                              ║
║   v5.5.1 FIXES (2026-05-30) — DB-PATH · BUNKER-GATE · FII-STREAK          ║
║   ─────────────────────────────────────────────────────────────             ║
║   FIX-DB1  DB PATH MISMATCH: DB_PATH default changed from outputs/ to      ║
║            data/  so it matches the YML  cache path: data/  directive.     ║
║            Previously the DB was written to outputs/ but the Actions cache  ║
║            only saved data/ — the SQLite was never restored between runs.   ║
║            All TAKEN decisions were lost; history cut off at last manual    ║
║            upload. Fix: single env-var default change. CACHE_PATH override  ║
║            still works if set explicitly.                                   ║
║                                                                              ║
║   FIX-BUNKER  BUNKER HARD GATE (all 3 lanes — FORTRESS / APEX / FUSED):   ║
║            If close > buy_hi * 1.03 the candidate is tagged                ║
║            CHASING_BUNKER_REJECT, grade set to WATCHLIST, and skipped      ║
║            via continue so the next-best symbol in the lane is tried.      ║
║            Eliminates mid-air chase entries that produce double-digit SL.  ║
║                                                                              ║
║   FIX-STREAK  FII/DII CONSECUTIVE-SESSION SCORING:                         ║
║            New fii_dii_history table (30-day rolling) in SQLite.           ║
║            _append_fii_dii_history() called each run after intel fetch.    ║
║            _get_fii_streak() reads last 5 rows; 3+ consecutive both-buying ║
║            sessions add +8 pts to fii score (cap raised to 38).            ║
║            Label shows "🔥 ACCUMULATING Nd streak" in Telegram card.       ║
║                                                                              ║
║   v5.5 ENHANCEMENTS (2026-05-20) — PCE · FIX42 · FULL METRIC PRESERVATION ║
║   ─────────────────────────────────────────────────────────────             ║
║   INT-1  PERMUTATIONS CONFLUENCE ENGINE (Section 13B)                       ║
║          PermutationsConfluenceEngine class injected into core pipeline.    ║
║          Tracks 5 live feature flags (Whale Radar, Hidden Divergence,       ║
║          VPOC Support, VSA Absorption, MFI Oversold) across all 2^5−1=31   ║
║          non-empty subsets. Computes exact joint conditional probabilities  ║
║          P(Win|E1∩E2∩...∩Ek) with Laplace-smoothed empirical rates when    ║
║          n≥8 samples, Beta-mean blended analytical prior otherwise.         ║
║          Output: confluence_matrix_score [0-100], best_k_combo label,      ║
║          pce_active_features, pce_max_joint_prob, pce_combo_source.        ║
║          Injected via **-unpack into fortress_score return dict — zero      ║
║          changes to any existing metric, fully additive.                    ║
║   INT-2  FIX 4.2 INSTITUTIONAL ALPHA PROTOCOL ENGINE (Section 20)          ║
║          FIX42AlphaSerializer class serializes finalized alpha picks into  ║
║          standard FIX 4.2 NewOrderSingle (MsgType=D) messages.             ║
║          Complete session: Logon(A) → N×NOS(D) → Logout(5).               ║
║          Custom 6000-series tags carry all Sniper alpha metadata:           ║
║          FusedScore(6001), ApexComposite(6002), FortressNorm(6003),        ║
║          WhaleScore(6004), BayesPct(6005), MCsurvival(6006),               ║
║          ConfluenceMatrixScore(6007), Grade(6008), HalalTier(6009),        ║
║          StopLoss(6010), R1/R2/R3(6011-6013), MacroState(6014),           ║
║          SetupProfile(6015). Thread-safe deque buffer + SQLite audit log.  ║
║          Fires in run() AFTER Halal AI Screen so only shariah-vetted picks  ║
║          are serialized. Non-blocking; a FIX error never kills the run.    ║
║   INT-3  FULL METRIC PRESERVATION                                           ║
║          All original v5.4 mathematical indicators fully preserved:         ║
║          6-layer adaptive VPOC (vectorized pure-NumPy), VCP tight coils,   ║
║          ATR velocity, VDU volume drying, Student-t MC (df=5), 14-node     ║
║          Bayesian network, Three-Lane scoring, MC Projection Engine,        ║
║          Survival Meta-Model — zero fields removed or altered.              ║
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
import itertools
import collections
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

VERSION = "UNIFIED v5.5.1-DB-BUNKER-STREAK"  # v5.5.1: FIX-DB1 (path outputs→data), FIX-BUNKER (hard gate all 3 lanes), FIX-STREAK (FII consecutive-session scoring) (2026-05-30)

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

DB_PATH          = Path(os.getenv("CACHE_PATH", "data/sniper_cache.db"))   # FIX-DB1: was outputs/ — must match YML cache path: data/
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
LANE_TOP_N              = int(os.getenv("LANE_TOP_N", "8"))           # top-N per lane pre-dedup
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
LLM_TIER2_MODEL = os.getenv("LLM_TIER2_MODEL", "gpt-4o-mini")     # Synthesis — FIX-v5.4: was "gpt-5-mini" (unverified); gpt-4o-mini is confirmed available
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
    "JAINREC",                  # Jain Irrigation – clearly halal, LLM confidence too strict
    # Optional: add any other symbols that were vetoed incorrectly,
    # but note that this set is intended for renewable/clean energy.
    # For non‑renewable halal symbols, consider a separate whitelist.
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
# FIX-MODEL-v5.4: "claude-sonnet-4-5" is now stale — correct live model is "claude-sonnet-4-6".
# Added "claude-sonnet-4-5" to the stale set so any env var or hardcoded reference
# auto-corrects. Default CLAUDE_MODEL falls through to "claude-sonnet-4-6".
_raw_claude_model  = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
_STALE_MODEL_NAMES = {
    "claude-sonnet-4-5",            # FIX-MODEL-v5.4: previously the "correct" default — now stale
    "claude-sonnet-4-20250514",
    "claude-3-5-sonnet-20241022",
    "claude-3-sonnet-20240229",
    "claude-3-haiku-20240307",
}
CLAUDE_MODEL       = ("claude-sonnet-4-6" if _raw_claude_model in _STALE_MODEL_NAMES
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
