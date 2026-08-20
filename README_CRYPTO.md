# FORTRESS_CRYPTO — Radar → Ignition → Execution, crypto horizon

An additive extension of FORTRESS_UNIFIED, not a rewrite. The equity
(NSE) pipeline is untouched — every file under `core/` and `workflows/`
without `crypto` in the name still does exactly what it did before. This
document covers what's new under `core/crypto/` and `workflows/*_crypto.py`.

## Why this is a separate system, not a reskin

The equity Incubator's edge is fundamentals (P/E, ROE, debt/equity,
insider/pledge data) plus a Shariah debt-ratio screen — none of which
exists in standardized form for crypto assets. Rather than force-fit
crypto data into equity-shaped gates, this build keeps the **architecture**
(bridge pattern, SQLite state, scoring pipeline, Telegram/Sheets output,
weekly LLM review loop) and rebuilds the **domain logic** from scratch for
what crypto data actually offers. See the conversation that produced this
build for the full reasoning on why a straight port would have been wrong.

## What's genuinely new

| Module | Role | Equity analogue |
|---|---|---|
| `core/crypto/config.py` | Crypto-specific tunables (universe, risk, cadence) | `core/config.py` |
| `core/crypto/data.py` | CoinGecko (universe/OHLC) + Binance (live price) cascade | `core/nse_data.py` |
| `core/crypto/onchain.py` | EVM-only whale/holder-concentration signal | `core/order_flow.py` |
| `core/crypto/shariah_crypto.py` | Categorical halal screen (no balance sheet to run ratios against) | `core/shariah.py` |
| `core/crypto/factors_crypto.py` | Momentum (vs BTC) + NVT-proxy value + on-chain quality Z-score model | `core/factors.py` |
| `core/crypto/bridge_crypto.py` | Pearl watchlist + ignition detection + unified conviction | `core/bridge.py` |
| `workflows/incubator_weekly_crypto.py` | Weekly pearl-finder | `workflows/incubator_weekly.py` |
| `workflows/sniper_daily_crypto.py` | Daily ignition scan | `workflows/sniper_daily.py` |
| `scripts/check_entry_crypto.py` | Live-price entry validity (staleness guard) | `scripts/check_entry.py` |
| `.github/workflows/crypto_daily.yml`, `crypto_weekly.yml` | GHA schedules | `daily.yml`, `weekly.yml` |

Data persists in the SAME `outputs/fortress_unified.db` SQLite file, under
`crypto_*`-prefixed tables — no schema or row overlap with the equity
tables, so a symbol collision can never cross-contaminate either bridge.

## Deliberate design decisions (and why)

1. **Top 200 by market cap universe.** Broad enough to find overlooked
   mid-caps, narrow enough that liquidity is real and free-tier CoinGecko
   rate limits stay usable on a weekly/daily cadence.
2. **On-chain scope: EVM chains only (Ethereum/BSC/Polygon), free
   Etherscan-family APIs.** Solana and other non-EVM chains get
   `on_chain_score = None` (treated as statistically neutral, never as a
   bad score) rather than fabricated coverage. This is an honest v1 gap,
   not an oversight — full multi-chain coverage needs a paid provider
   (Nansen/Glassnode).
3. **Staking/liquid-staking-derivative tokens are rejected outright** in
   the Shariah screen, per your explicit choice — this sidesteps rather
   than resolves the genuine, unsettled scholarly disagreement on whether
   PoS yield is riba.
4. **Crypto-specific risk sizing**, deliberately more conservative than
   the equity Kelly/ATR defaults (half the risk-per-trade %, more closed
   trades required before trusting Kelly, wider ATR stop multiples) —
   crypto's routine 70-90% drawdowns are not the tail event equity sizing
   assumes.
5. **"Value" factor uses inverse NVT-proxy** (market cap / 24h reported
   volume), explicitly labeled as a weaker proxy than true on-chain NVT
   (CoinGecko doesn't expose real on-chain transfer volume for most
   tokens) — the module docstring says so rather than presenting it as
   equivalent to equity P/E.
6. **Momentum is measured against BTC**, not an index — BTC is crypto's
   de facto beta anchor, the closest analogue to NIFTY-relative residual
   return in the equity factor model.

## What this deliberately does NOT attempt (v1)

- The legacy sniper's 14-node Bayesian engine, whale/order-flow scoring,
  and meta-labeler veto are **not ported** to crypto — `sniper_daily_crypto.py`
  uses a simpler RSI/ADX/volume-ratio composite for the trigger score.
  Porting the Bayesian engine is a real, buildable next step, same
  "flagged, not silently dropped" discipline as the equity README's own
  stub list.
- No genuine backtested validation of the ATH-discount "rubble" gate or
  the ignition thresholds has been run yet — these are reasoned defaults,
  not proven-in-production numbers. Treat the first several weeks as
  paper-trade validation, same caution the equity system's own README
  urges for anything not yet live-tested.
- Macro regime scoring (`_macro_subscore()` in `sniper_daily_crypto.py`)
  is a placeholder neutral 50.0 — NSE's VIX-based regime model has no
  clean crypto equivalent ported yet (BTC's own realized volatility could
  serve this role, flagged as a future addition).
- HFT, market-making, and true statistical arbitrage remain explicitly
  out of scope, same reasoning as the equity README.

## Setup

1. `pip install -r requirements.txt` (no new dependencies needed — pandas/
   numpy/requests already cover the crypto modules).
2. Existing secrets (`TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `GOOGLE_SHEET_ID`,
   `GOOGLE_CREDS_JSON`) are reused as-is.
3. New OPTIONAL secrets: `COINGECKO_API_KEY` (raises free-tier rate limit,
   not required), `ETHERSCAN_API_KEY` / `BSCSCAN_API_KEY` /
   `POLYGONSCAN_API_KEY` (each optional — missing key just means that
   chain's on-chain leg is skipped, fail-safe).
4. New Sheets tabs (auto-created on first write, except the halal list):
   `CRYPTO_INCUBATOR`, `CRYPTO_SCREENER`, `CRYPTO_REJECTS_LOG`. Seed
   `CRYPTO_HALAL_LIST` yourself (column A = symbol) if you want manual
   overrides of the categorical Shariah screen.
5. `.github/workflows/crypto_daily.yml` and `crypto_weekly.yml` run on
   schedule once pushed to `main`; use "Run workflow" to test manually
   first, same as the equity workflows.
