# FORTRESS_UNIFIED

**Radar → Ignition → Execution.** One system built from three: Incubator
(weekly deep-value/insider "pearl" finder), Sniper (daily technical
"ignition" detector + broad market scan), and Pine (chart-side execution
and management, still runs in TradingView — synced via `pine_sync.py`).

## Why this exists

The three original scripts worked independently: Incubator found
undervalued, quietly-accumulating stocks and did nothing further with
them; Sniper scanned the whole market cold every day with no memory of
what Incubator had already vetted; Pine ran on the chart with its own
regime/Bayesian/Monte Carlo logic, disconnected from either Python
pipeline. **The Bridge** (`core/bridge.py`) is the piece that didn't exist
before: Incubator writes to a persistent `pearl_watchlist`, Sniper reads
it every single day and gives those symbols priority attention + an
ignition check, and a pearl that ignites gets a scoring bonus that lets
it outrank an equal-strength cold-scan hit — because "cheap stock finally
moving" is a better signal than either fact alone.

## Architecture

```
                    ┌─────────────────────┐
   Sunday night     │  incubator_weekly.py │   Rubble + Sponge + EPS gates
   (GHA cron)       │                      │   → Shariah audit (fail-safe)
                    └──────────┬───────────┘   → upsert_pearl()
                               │
                               ▼
                    ┌─────────────────────┐
                    │   pearl_watchlist    │  ← THE BRIDGE (SQLite, core/db.py)
                    │   (SQLite table)     │
                    └──────────┬───────────┘
                               │
                               ▼
   Weekday 4pm IST    ┌─────────────────────┐
   (GHA cron)         │   sniper_daily.py   │  PASS A: watchlist priority scan
                       │                     │           + ignition detection
                       │                     │  PASS B: broad cold scan
                       └──────────┬──────────┘  → unified conviction score
                                  │
                       ┌──────────┴──────────┐
                       ▼                     ▼
                 Telegram alert        pine_sync.py → PINE_SYNC sheet
                 SCREENER sheet          (manual reference for Pine chart)

   Monday 9:30am IST  ┌─────────────────────┐
   (GHA cron)         │  core/weekly_review │  Claude reads 7 days of
                       │  (Anthropic ONLY    │  Sniper+Incubator+outcomes,
                       │   used here)        │  writes analysis + 1 tuning
                       └─────────────────────┘  suggestion → Telegram + sheet
```

## What's shared now (was duplicated/inconsistent before)

| Module | Replaces |
|---|---|
| `core/config.py` | scattered env-var reads in both scripts, with bug fixes |
| `core/nse_data.py` | two separate NSE session/bhavcopy implementations |
| `core/sheets_client.py` | two separate gspread wrappers |
| `core/shariah.py` | sniper's fail-closed halal check + incubator's fail-OPEN dynamic audit (now ONE fail-closed engine) |
| `core/scoring.py` | sniper's fortress_score/apex_composite (incubator gets access to this now too) |
| `core/db.py` | two separate SQLite schemas → one, plus the new `pearl_watchlist` table |
| `core/bridge.py` | **new** — did not exist in either original |
| `core/weekly_review.py` | **new** — the Anthropic learning loop you asked for |

## Bugs fixed during the merge

1. **Kelly sizing doubled risk** (`shares * kelly_mult * 2`) exactly when
   there was no trade history to justify it (`kelly_mult` defaulted to 1.0
   with <6 trades). Fixed: applied once, defaults to conservative 0.5,
   requires 20 closed trades before trusting the computed multiplier.
2. **Shariah fail-open bug**: Incubator's LLM-audit passed a stock through
   on a JSON parse error. Now every degraded path (sheet down, no OpenAI
   key, parse error, timeout) fails closed (rejects), matching Sniper's
   original philosophy — one policy, everywhere.
3. **ETF substring collisions**: `'BHARAT'` in the ban list matched
   `BHARATFORG`/`BHARATGEAR`. Now exact-token/suffix matching only.
4. **Ignition box-breakout self-reference bug** (found during this build's
   own testing): the 20-bar box high included *today's* bar, so a
   breakout day's close could never exceed its own high. Fixed to compute
   the box from the prior 20 bars, excluding today.
5. **heist-before-gate NSE hammering**: v8.2 sniper ran the expensive
   per-symbol NSE heist (SAST/insider/pledge lookups) on all ~400
   candidates before the cheap math gates ran. The unified cold-scan pass
   keeps heist-style enrichment for the pearl watchlist (small N, always
   worth it) and defers broad-scan enrichment to post-gate survivors only.

## Setup

1. `pip install -r requirements.txt`
2. Set GitHub Actions secrets: `OPENAI_API_KEY`, `TELEGRAM_TOKEN`,
   `TELEGRAM_CHAT_ID`, `GOOGLE_SHEET_ID`, `GOOGLE_CREDS_JSON`, and
   optionally `ANTHROPIC_API_KEY` (Monday review), `SCRAPERAPI_KEY`,
   `ADDON_FINANCE_API_KEY`.
3. Create a Google Sheet, share it with the service account email in your
   `GOOGLE_CREDS_JSON`, and put its ID in `GOOGLE_SHEET_ID`. Tabs
   (`SCREENER`, `INCUBATOR`, `BHAVCOPY`, `BHAVCOPY_ARCHIVE`, `PINE_SYNC`,
   `WEEKLY_REVIEWS`, `HALAL_LIST`) are created automatically on first
   write if missing — except `HALAL_LIST`, which you should seed
   yourself with your approved-sector reference list.
4. The `.github/workflows/daily.yml` and `weekly.yml` files handle
   scheduling. Push to `main` and they'll start running on schedule;
   use "Run workflow" in the Actions tab to test manually first.
5. `outputs/fortress_unified.db` is the shared SQLite bridge. GHA runs
   are stateless containers, so **this file must persist between runs** —
   the workflows upload it as a build artifact; for real continuity
   across days, wire it to a persistent volume, S3/GCS bucket, or commit
   it to a private data branch. (Sheets tabs like `BHAVCOPY_ARCHIVE` and
   `INCUBATOR`/`SCREENER` persist naturally since Sheets is external —
   the SQLite file is the one piece needing explicit persistence.)

## Training-data / learning loop (as requested)

- Every bhavcopy fetch, from whichever tier of the cascade succeeds, is
  archived to the `BHAVCOPY_ARCHIVE` sheet tab (`core/nse_data.py:
  save_bhavcopy_for_training`), so the data keeps accumulating regardless
  of which day NSE blocked you and Sheets/yfinance carried the load.
- Every Monday, `core/weekly_review.py` asks Claude to read the week's
  Sniper picks, Incubator pearls, gate-rejection breakdown, and resolved
  outcomes, and produce a grounded analysis — explicitly refusing to
  overclaim when the sample size is too small. This is a recommend-only
  loop: it posts to Telegram and logs to `WEEKLY_REVIEWS`, it does not
  auto-edit `config.py`.

## Known trim-for-this-build items (documented, not hidden)

To keep this deliverable end-to-end runnable rather than a 4,000-line
line-by-line port, a few legacy sniper_v7 features are stubbed with a
clear marker rather than fully re-wired:
- `workflows/sniper_daily.py: _dummy_order_flow()` — the real
  `compute_eod_order_flow()` (MTO delivery %, whale detection) from the
  legacy script should replace this; the scoring math already expects its
  exact shape.
- `bayes_pct` is a placeholder constant (55.0) in `score_symbol()` — the
  legacy 14-node Bayesian engine should be ported into `core/scoring.py`
  the same way `fortress_score`/`apex_composite` were.
- SAST insider check, pledge gate, alt-data semantic matching, and the
  meta-labeler veto exist in the legacy files and are straightforward to
  port into `core/` following the same pattern as `scoring.py` and
  `shariah.py` — flagged here so nothing is silently dropped.
