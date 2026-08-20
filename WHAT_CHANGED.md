# v1.1 — "diving skill" upgrade

## Files: what to do with each
- `core_crypto/config.py` → REPLACE your existing `core/crypto/config.py`
  entirely (adds daily-swing tier + news/trend constants, keeps
  everything from before intact).
- `core_crypto/news_sentiment.py` → NEW FILE. Add to `core/crypto/`
  (same folder as data.py, bridge_crypto.py etc.)
- `sniper_daily_crypto.py` → REPLACE your existing
  `workflows/sniper_daily_crypto.py` entirely.
- `incubator_weekly_crypto.py` → REPLACE your existing
  `workflows/incubator_weekly_crypto.py` entirely.
- `crypto_daily.yml` → REPLACE your existing
  `.github/workflows/crypto_daily.yml` (adds the new optional
  CRYPTOPANIC_API_KEY secret pass-through).

## What actually changed and why

### 1. Fixed daily always returning 0
`LANE_FUSED_MIN=60` was calibrated for "fortress-grade" setups — the
SAME bar as the weekly Incubator's best pearls. A daily 10-20%-target
swing trade is a genuinely different, lower-conviction, shorter-horizon
category. It now has its own bar (`DAILY_SWING_MIN=42`) instead of a
globally-lowered threshold that would've blurred fortress-grade and
swing-grade signals together. Alerts are now split into two clearly
labeled tiers.

### 2. Trend context (the first "diving skill" layer)
Free — uses data already fetched (7d/30d % change), no new API calls.
A setup fighting its own downtrend gets penalized; a setup WITH the
trend gets a bonus, even at equal raw technical score. Shown in every
alert as "Trend: UPTREND/DOWNTREND/SIDEWAYS".

### 3. News sentiment (the second "diving skill" layer)
New optional integration with CryptoPanic (free tier, needs a free
signup for an auth_token at cryptopanic.com/developers/api — add it as
secret `CRYPTOPANIC_API_KEY`). Applied ONLY to the shortlist that
already cleared the technical bar, not the whole 150-coin scan — same
"read the news on your shortlist, not on everything" logic a human
analyst would use, and it keeps free-tier call volume sane. Without the
key, alerts just say "News: n/a" rather than fabricating a sentiment.

### 4. Entry/exit timing
Every alert now shows:
  - Exact UTC timestamp of this scan run as the entry reference time
  - An ESTIMATED days-to-target for both T1 and T2, derived from the
    coin's own ATR (volatility) — explicitly an estimate, not a promise
  - Target range labeled per tier: Fortress/Pearl = 25-50%, Swing = 10-20%

## Honest caveats (same discipline as before)
- Trend/news are simple, auditable signals (7d/30d % change; CryptoPanic
  community vote balance) — not a proprietary edge or a trained model.
  They're meaningfully better than nothing, not a guarantee.
- Hold-day estimates are a coarse heuristic (ATR-implied), not backtested
  against actual crypto price-path data yet.
- None of the new target percentages (10-20% swing, 25-50% pearl) are
  validated against historical outcomes — they're reasoned defaults you
  should track against real results before trusting them.
