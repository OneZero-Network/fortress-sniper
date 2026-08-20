# Where each file goes in your existing repo

This zip contains ONLY new/crypto-specific files — nothing that overwrites
your existing equity pipeline. Copy them into your repo at these exact paths:

    core_crypto/                       →  core/crypto/            (rename the folder)
    workflows/incubator_weekly_crypto.py  →  workflows/incubator_weekly_crypto.py
    workflows/sniper_daily_crypto.py      →  workflows/sniper_daily_crypto.py
    scripts/check_entry_crypto.py         →  scripts/check_entry_crypto.py
    .github/workflows/crypto_daily.yml    →  .github/workflows/crypto_daily.yml
    .github/workflows/crypto_weekly.yml   →  .github/workflows/crypto_weekly.yml
    README_CRYPTO.md                      →  README_CRYPTO.md

ONE FILE NEEDS A MANUAL EDIT (not overwrite):
    Open your EXISTING core/db.py and paste the contents of
    db_py_addition_snippet.py onto the END of that file. Nothing else in
    db.py changes — this only adds one new function (init_crypto_tables).

Every other file here is brand new — none of them exist in your current
repo yet, so there's no merge conflict risk. requirements.txt does NOT
need any changes — pandas/numpy/requests (already there) cover everything.
