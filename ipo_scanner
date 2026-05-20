#!/usr/bin/env python3
"""
SME IPO SNIPER – Halal IPO Screener with Time‑to‑Close Dynamics
Reuses halal_ai_screen() from sniper_unified_v5_5.py.
"""

import os
import sys
import re
import json
import time
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
from bs4 import BeautifulSoup

# Import your existing halal engine (ensure the file is in the same directory)
from sniper_unified_v5_5 import (
    halal_ai_screen,
    _tg_post,
    _db_conn,
    _init_db,
    get_halal_universe,
    secrets,
    TELEGRAM_TOKEN,
    TELEGRAM_CHAT_ID,
    ACCOUNT_EQUITY,
    ACCOUNT_RISK_PCT,
    VERSION
)

# Configure logging (same format as sniper)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

VERSION_IPO = "IPO-SNIPER-v1.0"

# Constants
IPO_DB_PATH = Path("outputs/ipo_cache.db")   # separate DB for IPO results
MAX_SCORE = 100
# Scoring weights (additive, not multiplicative)
W_GMP = 0.30
W_SUB = 0.45
W_SIZE = 0.10
W_HALAL = 0.15

# Time‑to‑close factor: start of week = lower weight on subscription,
# last day = full weight. This models how subscription numbers evolve.
TIME_FACTOR_START = 0.40   # first day weight for subscription
TIME_FACTOR_END   = 1.00   # last day weight

# Sources
IPO_SOURCES = {
    "ipowatch": "https://ipowatch.in/upcoming-sme-ipo/",
    "chittorgarh": "https://www.chittorgarh.com/ipo/upcoming_sme_ipo.asp",
    "investorgain": "https://investorgain.com/ipo/upcoming-ipo"
}

# Static fallback dataset (create a CSV with at least columns: Symbol, IssueSizeCr, PriceBandLower, PriceBandUpper, LotSize, CloseDate)
FALLBACK_CSV = Path("data/ipo_fallback.csv")

# ----------------------------------------------------------------------
# 1. Data fetching with fallback
# ----------------------------------------------------------------------

def fetch_ipo_calendar() -> pd.DataFrame:
    """Primary: scrape IPO Watch for live SME IPO data.
       Returns DataFrame with columns:
       Symbol, IssueSizeCr, PriceBandLower, PriceBandUpper, LotSize,
       GMP, SubscriptionTimes, CloseDate, DaysToClose, Source.
    """
    try:
        url = IPO_SOURCES["ipowatch"]
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, headers=headers, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")

        # Find the main IPO table (adjust selector after inspecting site)
        table = soup.find("table", class_="table table-striped")
        if not table:
            log.warning("IPO table not found on ipowatch.in")
            return pd.DataFrame()

        rows = table.find_all("tr")[1:]  # skip header
        data = []
        today = datetime.today().date()

        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 6:
                continue
            # Extract fields (these class names are examples – adapt to actual site)
            symbol = cols[0].get_text(strip=True)
            price_band_text = cols[1].get_text(strip=True)
            issue_size_text = cols[2].get_text(strip=True).replace("₹", "").replace(" Cr", "")
            gmp_text = cols[3].get_text(strip=True).replace("%", "").replace("~", "")
            sub_text = cols[4].get_text(strip=True).replace("x", "").replace("times", "")
            close_date_text = cols[5].get_text(strip=True)

            # Parse price band
            price_band_lower, price_band_upper = 0, 0
            if "-" in price_band_text:
                parts = price_band_text.split("-")
                price_band_lower = float(parts[0].strip())
                price_band_upper = float(parts[1].strip())
            else:
                price_band_lower = price_band_upper = float(price_band_text)

            # Parse issue size (in crore)
            try:
                issue_size = float(issue_size_text)
            except:
                issue_size = 0.0

            # GMP (as percentage of upper price band)
            try:
                gmp = float(gmp_text) / 100.0 if gmp_text else 0.0
            except:
                gmp = 0.0

            # Subscription (times subscribed)
            try:
                sub_times = float(sub_text)
            except:
                sub_times = 0.0

            # Close date
            try:
                close_date = datetime.strptime(close_date_text, "%d-%b-%Y").date()
            except:
                close_date = today + timedelta(days=5)  # fallback

            days_to_close = (close_date - today).days

            data.append({
                "Symbol": symbol,
                "IssueSizeCr": issue_size,
                "PriceBandLower": price_band_lower,
                "PriceBandUpper": price_band_upper,
                "LotSize": 0,   # not always available, can be added
                "GMP": gmp,
                "SubscriptionTimes": sub_times,
                "CloseDate": close_date.strftime("%Y-%m-%d"),
                "DaysToClose": days_to_close,
                "Source": "ipowatch"
            })

        df = pd.DataFrame(data)
        if not df.empty:
            log.info(f"✅ Fetched {len(df)} IPOs from ipowatch.in")
            return df

    except Exception as e:
        log.warning(f"ipowatch.in scrape failed: {e}")

    # Fallback to static CSV
    if FALLBACK_CSV.exists():
        df = pd.read_csv(FALLBACK_CSV)
        # Add DaysToClose if not present
        if "DaysToClose" not in df.columns:
            today = datetime.today().date()
            df["DaysToClose"] = df["CloseDate"].apply(
                lambda x: (datetime.strptime(x, "%Y-%m-%d").date() - today).days
            )
        log.info(f"⚠️ Using static fallback CSV: {len(df)} IPOs")
        return df

    log.error("No IPO data source available")
    return pd.DataFrame()


# ----------------------------------------------------------------------
# 2. Scoring engine with time‑dependent subscription weight
# ----------------------------------------------------------------------

def compute_ipo_score(row: pd.Series) -> Dict:
    """Return dict with score (0-100), components, and verdict."""
    # Time factor: linear interpolation between start and end based on DaysToClose
    days = max(0, row.get("DaysToClose", 5))
    # Normalise: max days = 7 (typical IPO week). If days > 7, factor = end.
    max_days = 7
    if days >= max_days:
        time_factor = TIME_FACTOR_END
    else:
        # Interpolate: factor = start + (end - start) * (1 - days/max_days)
        time_factor = TIME_FACTOR_START + (TIME_FACTOR_END - TIME_FACTOR_START) * (1 - days / max_days)
    time_factor = max(TIME_FACTOR_START, min(TIME_FACTOR_END, time_factor))

    # 1. GMP score (0-30)
    gmp = max(0.0, min(0.50, row.get("GMP", 0.0)))   # cap GMP at 50%
    score_gmp = gmp * 100 * W_GMP   # e.g., 20% GMP -> 20 * 0.30 = 6 pts

    # 2. Subscription score (0-45) – weighted by time factor
    # Raw subscription: cap at 50x (beyond that gives no extra)
    sub_raw = min(50.0, row.get("SubscriptionTimes", 0.0))
    # Convert to 0-1 scale: 0x = 0, 25x = 0.75, 50x = 1.0
    sub_norm = sub_raw / 50.0
    score_sub = sub_norm * MAX_SCORE * W_SUB * time_factor

    # 3. Issue size score (0-10) – smaller is better
    size = row.get("IssueSizeCr", 100.0)
    if size <= 20:
        score_size = 10
    elif size <= 50:
        score_size = 8
    elif size <= 100:
        score_size = 6
    elif size <= 250:
        score_size = 4
    else:
        score_size = 2
    score_size = score_size * (W_SIZE / 0.10)   # normalise (max 10 → 10% weight)

    # 4. Halal score (0-15) – will be filled later
    # We'll call halal_ai_screen separately and merge
    halal_score = 0.0  # placeholder

    raw_score = score_gmp + score_sub + score_size + halal_score
    final_score = min(MAX_SCORE, max(0, int(round(raw_score))))

    # Verdict (same flags as sniper)
    if final_score >= 75:
        verdict = "WORTH YOUR TIME"
        flag_emoji = "🟢"
    elif final_score >= 55:
        verdict = "MAYBE"
        flag_emoji = "🔵"
    else:
        verdict = "SKIP"
        flag_emoji = "⚪"

    return {
        "score": final_score,
        "score_gmp": round(score_gmp, 1),
        "score_sub": round(score_sub, 1),
        "score_size": round(score_size, 1),
        "time_factor": round(time_factor, 3),
        "verdict": verdict,
        "flag_emoji": flag_emoji,
        "gmp_pct": round(gmp * 100, 1),
        "sub_times": sub_raw,
    }


# ----------------------------------------------------------------------
# 3. Halal enrichment (reuse your existing engine)
# ----------------------------------------------------------------------

def enrich_halal(df: pd.DataFrame) -> pd.DataFrame:
    """Add halal_score and halal_tier for each IPO."""
    scores = []
    tiers = []
    for _, row in df.iterrows():
        sym = row["Symbol"]
        # Build a minimal business description from the symbol (or look up later)
        # For now, use sector = "DIVERSIFIED"
        sector = "DIVERSIFIED"
        business_desc = f"SME IPO company {sym}"
        halal = halal_ai_screen(sym, sector=sector, business_desc=business_desc)
        scores.append(halal.get("score", 0))
        tiers.append(halal.get("tier", "UNKNOWN"))
    df["HalalScore"] = scores
    df["HalalTier"] = tiers
    return df


def adjust_score_with_halal(df: pd.DataFrame) -> pd.DataFrame:
    """Incorporate HalalScore (0-100) into the final IPO score (15% weight)."""
    # Normalise halal score to 0-15 range
    df["HalalContribution"] = (df["HalalScore"] / 100) * MAX_SCORE * W_HALAL
    df["FinalScore"] = (
        df["score_gmp"] + df["score_sub"] + df["score_size"] + df["HalalContribution"]
    )
    df["FinalScore"] = df["FinalScore"].clip(0, MAX_SCORE).astype(int)
    # Update verdict based on final score
    df["Verdict"] = df["FinalScore"].apply(
        lambda x: "WORTH YOUR TIME" if x >= 75 else ("MAYBE" if x >= 55 else "SKIP")
    )
    return df


# ----------------------------------------------------------------------
# 4. Database persistence (separate DB for IPO results)
# ----------------------------------------------------------------------

def init_ipo_db():
    """Create IPO-specific tables."""
    IPO_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _db_conn(write=True) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS ipo_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date TEXT,
                symbol TEXT,
                issue_size_cr REAL,
                price_lower REAL,
                price_upper REAL,
                lot_size INTEGER,
                gmp_pct REAL,
                sub_times REAL,
                close_date TEXT,
                days_to_close INTEGER,
                halal_score INTEGER,
                halal_tier TEXT,
                score_gmp REAL,
                score_sub REAL,
                score_size REAL,
                halal_contribution REAL,
                final_score INTEGER,
                verdict TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(run_date, symbol)
            )
        """)
    log.info("IPO DB initialised")


def save_ipo_results(df: pd.DataFrame, date_label: str):
    """Store daily IPO analysis."""
    with _db_conn(write=True) as con:
        for _, row in df.iterrows():
            con.execute("""
                INSERT OR REPLACE INTO ipo_analysis
                (run_date, symbol, issue_size_cr, price_lower, price_upper,
                 lot_size, gmp_pct, sub_times, close_date, days_to_close,
                 halal_score, halal_tier, score_gmp, score_sub, score_size,
                 halal_contribution, final_score, verdict)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                date_label, row["Symbol"], row["IssueSizeCr"],
                row["PriceBandLower"], row["PriceBandUpper"],
                row.get("LotSize", 0), row["gmp_pct"], row["SubscriptionTimes"],
                row["CloseDate"], row["DaysToClose"],
                row["HalalScore"], row["HalalTier"],
                row["score_gmp"], row["score_sub"], row["score_size"],
                row["HalalContribution"], row["FinalScore"], row["Verdict"]
            ))


# ----------------------------------------------------------------------
# 5. Telegram report (same style as sniper)
# ----------------------------------------------------------------------

def send_ipo_telegram(df: pd.DataFrame, macro_state: str, vix: float, date_label: str):
    """Send a clean IPO report card."""
    if df.empty:
        _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
                 f"⚔️ IPO SNIPER | {date_label} | {macro_state} | VIX {vix:.1f}\n\n🤲 No active SME IPOs today.")
        return

    # Sort by final score descending
    df_sorted = df.sort_values("FinalScore", ascending=False)
    lines = [
        f"⚔️ IPO SNIPER {VERSION_IPO} | {date_label} | Macro: {macro_state} | VIX {vix:.1f}",
        "🕌 Halal | Manual execution only",
        "─────────────────────────────────────"
    ]

    for i, (_, row) in enumerate(df_sorted.iterrows(), 1):
        sym = row["Symbol"]
        close_date = row["CloseDate"]
        days_left = row["DaysToClose"]
        price_band = f"₹{row['PriceBandLower']:.0f}–{row['PriceBandUpper']:.0f}"
        gmp = row["gmp_pct"]
        sub = row["sub_times"]
        score = row["FinalScore"]
        verdict = row["Verdict"]
        halal_tier = row["HalalTier"]
        halal_score = row["HalalScore"]

        # Extra note if subscription is still low but closing soon
        note = ""
        if days_left <= 2 and sub < 5 and gmp > 15:
            note = "\n   💡 Subscription may spike on final day – monitor."
        elif days_left <= 1:
            note = "\n   ⏰ Last day – consider applying if fundamentals strong."

        card = (
            f"#{i} {sym} – {verdict} ({score}/100)\n"
            f"   Price: {price_band} | Lot: {row.get('LotSize', '?')} shares\n"
            f"   Issue size: ₹{row['IssueSizeCr']:.0f}Cr | GMP: {gmp:.1f}%\n"
            f"   Subscription: {sub:.1f}x | Closes: {close_date} ({days_left} days left)\n"
            f"   Halal: {halal_tier} ({halal_score}/100)\n"
            f"   Score breakdown: GMP {row['score_gmp']:.0f} + Sub {row['score_sub']:.0f} + Size {row['score_size']:.0f} + Halal {row['HalalContribution']:.0f}{note}"
        )
        lines.append(card)
        lines.append("")

    lines.append("─────────────────────────────────────")
    lines.append("ℹ️ Reply: TAKEN SYMBOL | SKIP SYMBOL")
    lines.append(f"🤲 Bismillah – trade only what you understand")
    full_msg = "\n".join(lines)
    # Split if needed (reuse _split_msg from sniper)
    from sniper_unified_v5_5 import _split_msg
    for chunk in _split_msg(full_msg, 4000):
        _tg_post(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, chunk)


# ----------------------------------------------------------------------
# 6. Main run function
# ----------------------------------------------------------------------

def run_ipo_screener():
    """Main entry point for GitHub Actions."""
    # Initialise DB (reuse same init if you want, but we create IPO tables)
    _init_db()          # ensures main DB exists (for halal cache)
    init_ipo_db()

    # Fetch macro regime from your sniper (reuse function)
    from sniper_unified_v5_5 import fetch_macro_regime, _get_macro
    macro = _get_macro()
    macro_state = macro.get("macro_state", "CHOP")
    vix = macro.get("vix_val", 18.0)

    # Stop if market is in crash mode
    if macro_state in ("MASSACRE", "PANIC"):
        log.warning(f"Macro {macro_state} – skipping IPO analysis")
        send_ipo_telegram(pd.DataFrame(), macro_state, vix, datetime.today().strftime("%Y-%m-%d"))
        return

    # Fetch IPO data
    df = fetch_ipo_calendar()
    if df.empty:
        send_ipo_telegram(pd.DataFrame(), macro_state, vix, datetime.today().strftime("%Y-%m-%d"))
        return

    # Compute base scores (without halal)
    scores = df.apply(compute_ipo_score, axis=1, result_type="expand")
    for col in scores.columns:
        df[col] = scores[col]

    # Enrich with halal (runs LLM if needed – cached)
    df = enrich_halal(df)

    # Recompute final score including halal contribution
    df = adjust_score_with_halal(df)

    # Add close_date as string (already present)
    date_label = datetime.today().strftime("%Y-%m-%d")

    # Save to DB
    save_ipo_results(df, date_label)

    # Filter only IPOs with days left >= 0 (still open)
    df_active = df[df["DaysToClose"] >= 0].copy()

    # Send Telegram report
    send_ipo_telegram(df_active, macro_state, vix, date_label)

    log.info(f"IPO screener done – {len(df_active)} active IPOs evaluated")


if __name__ == "__main__":
    run_ipo_screener()
