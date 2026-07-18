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

## Second mentor-review round (debt threshold precision + live re-validation)

A follow-up live run surfaced three more real gaps:

1. **Debt threshold was looser than the standard actually being enforced.**
   The code used 0.45 for debt/equity while your mentor's manual review
   holds everything to 0.33 (Ala Hazrat's limit) — that's why DOLLAR
   (D/E 0.34), ARIS (D/E 1.61), and RSYSTEMS (D/E 0.49) passed the code
   but failed manual review. Fixed: `SHARIAH_MAX_DEBT_TO_EQUITY` now
   defaults to the SAME value as `SHARIAH_MAX_DEBT_TO_ASSETS` (0.33) — one
   threshold, one standard, set via a single config constant. Verified
   against all four of your mentor's flagged tickers.

   **Deliberately NOT changed:** FABTECH's D/E of 0.32 is under 0.33 and
   passes this screen by design — your mentor's rejection of it was an
   extra personal margin-of-safety judgment ("too close to the edge"), not
   evidence the 0.33 rule itself was violated. Per your explicit choice,
   the code keeps a hard line at 0.33 with no safety buffer; a stricter
   buffer would need to be a new, separately-named constant if you want it
   later — see the comment in `config.py` for the exact reasoning.

2. **MAXIND-style "wealth destroyers"** (clean debt ratios, catastrophic
   ROE/EPS) needed a gate the Shariah debt screen was never meant to be.
   Added `core/fundamentals.py: quality_veto()` — a genuinely separate
   hard-reject gate (not folded into Shariah, since "is the balance sheet
   halal-compliant" and "is this a viable business" are different
   questions with different fail-safe policies: missing ROE/EPS data does
   NOT veto, since this isn't a compliance gate). Verified against MAXIND's
   exact numbers (ROE -29.84%, EPS -23.17) → correctly rejected; IPL's
   healthy numbers → correctly passes; missing data → correctly passes
   through un-vetoed rather than blocking on a data gap.

3. **The ASPINWALL "ghost entry" problem** — the scanner's entry (₹257)
   and stop (₹240) were computed from yesterday's EOD close; by the time
   of manual review, live price had already drifted down onto the stop
   line. This is a scan-vs-action staleness gap that no amount of smarter
   scan-time scoring can fix — it needs a live check at the moment you're
   about to act. Built `scripts/check_entry.py`: run
   `python scripts/check_entry.py ASPINWALL` right before entering a
   position, and it fetches live price and tells you plainly whether the
   setup is BROKEN (price already hit/breached stop), CRITICAL (sitting
   within 1.5% of stop, exactly like the ASPINWALL case), DRIFTED (moved
   meaningfully from scan-time entry but still technically valid),
   TARGET_HIT (already past R1 — don't chase), or VALID. Verified against
   the exact ASPINWALL numbers: live price at ₹240 → BROKEN, ₹242 → CRITICAL,
   ₹258 → VALID. Also added a same-alert thin-margin warning in
   `sniper_daily.py` for setups whose scan-time entry/stop gap was already
   under 3% before any drift — a different, complementary check (catches
   inherently thin setups, not live drift).



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

## Intelligence upgrades (mentor-review response)

A live run surfaced two real gaps a manual review caught that the pipeline
couldn't: MTNL (₹31,944 Cr debt, NPA loans) passed Shariah because the old
check only looked at ticker keywords + sector name, never a balance sheet;
and several picks (EPIGRAL ₹1,068, SHARDACROP ₹893) exceeded a ₹300
block-accumulation ceiling that wasn't encoded anywhere. Both are now real,
automated gates — verified against the mentor's exact numbers:

- **`core/shariah.py: debt_ratio_screen()` (Layer 4)** — quantitative
  AAOIFI-style screen (debt/assets ≤ 33%, debt/equity ≤ 0.45 by default,
  both tunable in `config.py`). Fails safe (rejects) when debt data is
  unavailable, matching the fail-closed philosophy of L1-L3. Tested against
  synthetic MTNL-like ratios (65% debt/assets) → correctly rejects; IPL-like
  (5% debt/assets) → correctly passes.
- **`workflows/incubator_weekly.py: check_price_ceiling()`** — a *strategy*
  gate, deliberately separate from the liquidity `MIN_PRICE`/`MAX_PRICE`
  band, enforcing `config.PRICE_CEILING_BLOCK` (default ₹300) /
  `PRICE_FLOOR_BLOCK` (default ₹20). Tested against the mentor's own
  examples: EPIGRAL (₹1,068) → rejected, IPL (₹163) / ACL (₹49.35) → pass.
- **`core/factors.py` — Composite Z-Score factor model** (your friends'
  Method 1). Cross-sectional Z-scores for Momentum (63-day residual return
  vs NIFTY), Value (inverse P/E, falls back to inverse P/B), and Quality
  (ROE%), blended via configurable weights (`FACTOR_W_MOMENTUM/VALUE/QUALITY`,
  default 50/25/25) into one `z_composite` per pearl, written to the
  `INCUBATOR` sheet and used to re-rank pearls before they hit the
  watchlist. Below `FACTOR_MIN_UNIVERSE_N` (default 30) candidates, scores
  degrade to neutral (50.0) rather than producing unstable Z-scores off a
  too-small sample — tested and verified.
- **`core/macro_commentary.py`** — explicitly NOT a prediction engine
  (see module docstring for why "predict sector rotation from tariffs/
  dollar index" isn't something an LLM can responsibly claim to do). Asks
  for a labeled sector-level OPINION once every few hours, applies a
  small, hard-capped nudge (`MACRO_COMMENTARY_MAX_BONUS`, default ±5 pts
  on the 0-100 conviction scale) only when the LLM states confidence at
  or above `MACRO_COMMENTARY_MIN_CONFIDENCE` (default 0.6/"medium"), and
  logs the bonus + reasoning in its own `MacroBonus`/`MacroNote` columns
  in `SCREENER` so it's always distinguishable from and auditable against
  the technical/fundamental score — never silently folded in.
- **`core/fundamentals.py: debt_and_quality_ratios()`** — the new data
  layer both the debt screen and the Z-score model draw from (P/E, P/B,
  ROE%, debt/equity, debt/assets, total debt in ₹Cr), sourced from
  yfinance with `None` (not 0) on any unavailable field so downstream
  consumers never mistake missing data for a clean balance sheet.

### What this deliberately does NOT attempt

Per your friends' broader notes: HFT/market-making needs colocated
infrastructure this system will never have and isn't worth chasing.
Statistical arbitrage/pairs trading and a genuine regime-switching ML
meta-model (their Method 2) are real, buildable ideas but need dedicated
modules and real backtested validation before they should touch live
capital — flagged as a future addition, not built speculatively today.
"Predict the bounce"/RSI-divergence-as-prediction and 2pm auction-market
arbitrage are both real trader techniques but carry execution/slippage
risk that's inappropriate to automate without you first understanding
and manually validating the edge — these stay manual-watch items, not
automated gates.



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
