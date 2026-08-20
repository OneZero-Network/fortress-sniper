# Three real bugs fixed — 4 files, all REPLACE (not append)

## Bug 1: Pearls never carried over to the daily Sniper run
Root cause: `outputs/fortress_unified.db` (SQLite) never persisted between
GitHub Actions runs — every workflow run starts on a fresh runner with an
empty database, so PASS A always saw "0 active pearls" no matter what the
Incubator found. FIX: both workflow YAMLs now use `actions/cache` to save/
restore the DB file across runs, so pearls written this week are actually
there when the daily scan checks for ignition.

## Bug 2: No Telegram notification on the daily Sniper run
Not actually a bug in the alerting code — 0 candidates cleared the
LANE_FUSED_MIN threshold that day, so (correctly, per the old logic)
nothing was sent. But paired with Bug 1, silence was indistinguishable
from failure. FIX: both workflows now ALWAYS send a status message —
either the alert list, or an explicit "ran fine, 0 candidates today"
heartbeat — so you always know the job executed.

## Bug 3: Incubator alerts showed only grade/score, no buy/sell info
This was a genuine missing feature, not a display issue — entry/stop-
loss/target were never computed anywhere in the Sniper. FIX: added
ATR-based stop-loss and two profit targets (1.5R / 3R) to every Sniper
candidate, and the Telegram message now shows BUY price / SL / T1 / T2
for anything that clears the alert threshold. The Incubator's weekly
pearl message is now explicitly labeled as a WATCHLIST, not a trade
signal — buy/sell levels only ever come from the daily Sniper scan when
a real ignition/setup is detected, same separation of concerns as your
original equity system (Incubator finds candidates, Sniper times entries).

## Files to replace in your repo
- `workflows/sniper_daily_crypto.py` → replace entirely
- `workflows/incubator_weekly_crypto.py` → replace entirely
- `.github/workflows/crypto_daily.yml` → replace entirely
- `.github/workflows/crypto_weekly.yml` → replace entirely

## What to expect next run
- Incubator Telegram message will say "watchlist, not a trade signal"
- Sniper will either show BUY/SL/T1/T2 levels for real candidates, or
  send an explicit "ran fine, 0 candidates" message — never silence
- Give it ONE full incubator run + ONE full sniper run before judging
  whether pearls persist — the cache only has something to restore from
  after the first run following this fix
