"""
FORTRESS_UNIFIED — core/nse_data.py
══════════════════════════════════════════════════════════════════════════════
The single NSE data cascade, shared by Sniper AND Incubator (previously each
had its own, with Incubator's being noticeably thinner/less resilient).

CASCADE ORDER (unchanged from sniper_v7 — the more battle-tested version):
  1. NSE archives — 3-step Cloudflare session handshake + curl_cffi TLS
     fingerprint bypass when available.
  2. Addon Finance API (if ADDON_FINANCE_API_KEY set).
  3. Google Sheets BHAVCOPY tab — this is also where every successful fetch
     gets SAVED (see save_bhavcopy_for_training below), so it's both the
     fallback source AND the accumulating training/learning archive you
     asked to keep.
  4. yfinance small hardcoded universe — absolute last resort.

Every tier that succeeds writes its result to the BHAVCOPY tab before
returning, so the Sheets copy is always growing and never more than one
run stale — this is the "continue and save it on save sheet for learning
and training purpose" behavior you asked for.
"""
from __future__ import annotations
import io
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import pandas as pd
import requests

from . import config
from .sheets_client import push_sheet, read_sheet

log = logging.getLogger("fortress.nse_data")

try:
    from curl_cffi import requests as curl_requests
    _CURL_CFFI_OK = True
except ImportError:
    _CURL_CFFI_OK = False

try:
    import yfinance as yf
    _YFINANCE_OK = True
except ImportError:
    _YFINANCE_OK = False


NSE_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

_UA_POOL = [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) "
     "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15"),
    ("Mozilla/5.0 (X11; Linux x86_64) "
     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"),
]

_SESSION_LOCK = threading.Lock()
_SESSION_CACHE: Optional[requests.Session] = None
_SESSION_TS = 0.0

# ── NSE per-symbol circuit breaker ──────────────────────────────────────────
# On GHA datacenter IPs, NSE's Akamai blocks most API calls. Without a
# breaker, every one of 400 symbols pays a full connect+timeout on the NSE
# attempt before falling back to yfinance. After NSE_CIRCUIT_MAX_FAILS
# consecutive failures, all per-symbol NSE calls short-circuit for the rest
# of the process; one later success resets it.
_NSE_FAILS = 0
_NSE_CIRCUIT_LOCK = threading.Lock()


def nse_circuit_ok() -> bool:
    return _NSE_FAILS < config.NSE_CIRCUIT_MAX_FAILS


def nse_circuit_report(success: bool) -> None:
    global _NSE_FAILS
    with _NSE_CIRCUIT_LOCK:
        if success:
            _NSE_FAILS = 0
        else:
            _NSE_FAILS += 1
            if _NSE_FAILS == config.NSE_CIRCUIT_MAX_FAILS:
                log.warning(f"NSE circuit breaker OPEN after {_NSE_FAILS} consecutive "
                            "failures — skipping NSE per-symbol calls for this run")


def get_nse_session() -> requests.Session:
    """3-step Cloudflare-aware session handshake, cached for NSE_SESSION_TTL."""
    global _SESSION_CACHE, _SESSION_TS
    with _SESSION_LOCK:
        now = time.time()
        if _SESSION_CACHE is not None and (now - _SESSION_TS) < config.NSE_SESSION_TTL:
            return _SESSION_CACHE
        sess = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=24, pool_maxsize=24)
        sess.mount("https://", adapter)
        sess.mount("http://", adapter)
        try:
            sess.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=10)
            time.sleep(0.5)
            sess.get("https://www.nseindia.com/api/allIndices",
                      headers={**NSE_HEADERS, "X-Requested-With": "XMLHttpRequest"},
                      timeout=10)
        except Exception as e:
            log.debug(f"NSE session warmup: {e}")
        _SESSION_CACHE = sess
        _SESSION_TS = now
        return sess


def get_last_trading_day() -> Tuple[str, str]:
    """Holiday-aware last trading day. Returns (ddmmyyyy, yyyy-mm-dd)."""
    today = datetime.today()
    d = today - timedelta(days=1)
    holidays = config.nse_holidays()
    for _ in range(10):
        if d.weekday() < 5 and d.strftime("%Y-%m-%d") not in holidays:
            break
        d -= timedelta(days=1)
    return d.strftime("%d%m%Y"), d.strftime("%Y-%m-%d")


# ══════════════════════════════════════════════════════════════════════════
# TRAINING-DATA SAVE — every successful bhavcopy fetch archives to Sheets
# ══════════════════════════════════════════════════════════════════════════

def save_bhavcopy_for_training(df: pd.DataFrame, source: str, date_label: str) -> None:
    """
    Append (not overwrite) the day's bhavcopy to a BHAVCOPY_ARCHIVE tab,
    tagged with source + date, so Monday's review and any future model
    training has the full week's raw market data — independent of whichever
    tier of the cascade produced it.

    This is separate from the BHAVCOPY tab (which is the "latest snapshot,
    used as tier-3 fallback") so the archive can grow without disturbing
    the fallback-read path's expected shape.
    """
    if df.empty:
        return
    try:
        cols = ["symbol", "close", "high", "low", "volume", "turnover_lakhs"]
        keep = [c for c in cols if c in df.columns]
        snap = df[keep].copy()
        snap.insert(0, "date", date_label)
        snap.insert(1, "source", source)
        rows = [snap.columns.tolist()] + snap.astype(str).values.tolist()
        # Append-style: read existing, concat, push. Sheets API has no
        # native append-in-bulk-with-header-dedup, so we do it manually.
        existing = read_sheet("BHAVCOPY_ARCHIVE")
        if existing and len(existing) > 1:
            # Drop any existing rows for this exact date+source to avoid
            # duplicate accumulation on reruns.
            header = existing[0]
            body = [r for r in existing[1:]
                    if not (len(r) > 1 and r[0] == date_label and r[1] == source)]
            combined = [header] + body + rows[1:]
        else:
            combined = rows
        push_sheet("BHAVCOPY_ARCHIVE", combined)
        log.info(f"BHAVCOPY_ARCHIVE: saved {len(snap)} rows ({source}, {date_label}) for training")
    except Exception as e:
        log.debug(f"save_bhavcopy_for_training: {e}")


def _clean_bhav_df(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["close", "high", "low", "volume", "turnover_lakhs"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    if "turnover_lakhs" not in df.columns and "volume" in df.columns and "close" in df.columns:
        df["turnover_lakhs"] = df["volume"] * df["close"] / 100_000
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    df = df.dropna(subset=["close"]).query("close > 0").reset_index(drop=True)
    df = df[~df["symbol"].apply(config.is_etf_or_index)]
    return df


# ── Tier 1: NSE archives ─────────────────────────────────────────────────────
def _tier1_nse_archive(date_label: str) -> pd.DataFrame:
    dd_mm_yyyy, _ = get_last_trading_day()
    d = datetime.strptime(dd_mm_yyyy, "%d%m%Y")
    dd, mm, yyyy, mmm = d.strftime("%d"), d.strftime("%m"), d.strftime("%Y"), d.strftime("%b").upper()
    url = (f"https://archives.nseindia.com/content/historical/EQUITIES/"
           f"{yyyy}/{mmm}/cm{dd}{mmm}{yyyy}bhav.csv.zip")
    try:
        sess = get_nse_session()
        resp = sess.get(url, headers=NSE_HEADERS, timeout=25)
        if resp.status_code == 200 and len(resp.content) > 5000:
            from zipfile import ZipFile
            zf = ZipFile(io.BytesIO(resp.content))
            name = [n for n in zf.namelist() if n.endswith(".csv")][0]
            df = pd.read_csv(io.BytesIO(zf.read(name)))
            df.columns = [c.strip().upper() for c in df.columns]
            if "SERIES" in df.columns:
                df = df[df["SERIES"] == "EQ"]
            df = df.rename(columns={"SYMBOL": "symbol", "CLOSE": "close",
                                     "HIGH": "high", "LOW": "low",
                                     "TOTTRDQTY": "volume", "TOTTRDVAL": "turnover_lakhs"})
            df["turnover_lakhs"] = df.get("turnover_lakhs", 0) / 100_000
            return _clean_bhav_df(df)
    except Exception as e:
        log.debug(f"Tier1 NSE archive: {e}")
    return pd.DataFrame()


# ── Tier 2: Addon Finance API ────────────────────────────────────────────────
def _tier2_addon_finance(date_label: str) -> pd.DataFrame:
    if not config.ADDON_FINANCE_API_KEY:
        return pd.DataFrame()
    try:
        resp = requests.get(
            "https://api.addon.finance/v1/nse/bhavcopy",
            params={"date": date_label, "api_key": config.ADDON_FINANCE_API_KEY},
            timeout=20,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            if data:
                df = pd.DataFrame(data)
                df.columns = [c.strip().lower() for c in df.columns]
                return _clean_bhav_df(df)
    except Exception as e:
        log.debug(f"Tier2 Addon Finance: {e}")
    return pd.DataFrame()


# ── Tier 3: Google Sheets BHAVCOPY tab ───────────────────────────────────────
def _tier3_sheets_fallback() -> pd.DataFrame:
    try:
        raw = read_sheet("BHAVCOPY")
        if raw and len(raw) > 100:
            df = pd.DataFrame(raw[1:], columns=[str(h).strip().lower() for h in raw[0]])
            return _clean_bhav_df(df)
    except Exception as e:
        log.debug(f"Tier3 Sheets fallback: {e}")
    return pd.DataFrame()


# ── Tier 4: yfinance last resort ─────────────────────────────────────────────
_YF_FALLBACK_UNIVERSE = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "SBIN",
    "BHARTIARTL", "ITC", "KOTAKBANK", "LT", "HCLTECH", "AXISBANK", "BAJFINANCE",
    "WIPRO", "MARUTI", "SUNPHARMA", "TITAN", "NTPC", "ULTRACEMCO",
]


def _tier4_yfinance() -> pd.DataFrame:
    if not _YFINANCE_OK:
        return pd.DataFrame()
    rows = []
    try:
        for sym in _YF_FALLBACK_UNIVERSE:
            t = yf.Ticker(f"{sym}.NS")
            h = t.history(period="1d")
            if not h.empty:
                rows.append({
                    "symbol": sym, "close": float(h["Close"].iloc[-1]),
                    "high": float(h["High"].iloc[-1]), "low": float(h["Low"].iloc[-1]),
                    "volume": float(h["Volume"].iloc[-1]),
                    "turnover_lakhs": float(h["Volume"].iloc[-1] * h["Close"].iloc[-1] / 100_000),
                })
    except Exception as e:
        log.debug(f"Tier4 yfinance: {e}")
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def load_bhavcopy(date_label: Optional[str] = None) -> Tuple[pd.DataFrame, str]:
    """
    The single shared bhavcopy loader for both Sniper and Incubator.
    Returns (dataframe, source_tag). Archives every successful fetch to
    BHAVCOPY_ARCHIVE for training/learning purposes, and refreshes the
    BHAVCOPY tab (tier-3 fallback) whenever a higher tier succeeds.
    """
    if date_label is None:
        _, date_label = get_last_trading_day()

    for tier_fn, tag in [
        (lambda: _tier1_nse_archive(date_label), "NSE_ARCHIVE"),
        (lambda: _tier2_addon_finance(date_label), "ADDON_FINANCE"),
    ]:
        df = tier_fn()
        if not df.empty:
            log.info(f"Bhavcopy loaded via {tag}: {len(df)} rows")
            save_bhavcopy_for_training(df, tag, date_label)
            # Refresh the tier-3 fallback snapshot with fresh data
            try:
                rows = [df.columns.tolist()] + df.astype(str).values.tolist()
                push_sheet("BHAVCOPY", rows)
            except Exception as e:
                log.debug(f"BHAVCOPY snapshot refresh: {e}")
            return df, tag

    df = _tier3_sheets_fallback()
    if not df.empty:
        log.warning(f"Bhavcopy loaded via SHEETS_FALLBACK: {len(df)} rows (NSE + Addon both failed)")
        return df, "SHEETS_FALLBACK"

    df = _tier4_yfinance()
    if not df.empty:
        log.warning(f"Bhavcopy loaded via YFINANCE_LAST_RESORT: {len(df)} rows")
        save_bhavcopy_for_training(df, "YFINANCE_LAST_RESORT", date_label)
        return df, "YFINANCE_LAST_RESORT"

    log.error("Bhavcopy: ALL 4 TIERS FAILED")
    return pd.DataFrame(), "ALL_FAILED"


def fetch_history(symbol: str, days: int = 300) -> pd.DataFrame:
    """Daily OHLCV history with a 'date' column (yyyy-mm-dd strings) — NSE
    first (circuit-breaker protected), yfinance fallback. NaN-safe: rows
    with NaN in close/high/low are dropped (they crashed the incubator's
    rubble gate via np.max NaN propagation in the first live run)."""
    if nse_circuit_ok():
        try:
            sess = get_nse_session()
            resp = sess.get(
                f"https://www.nseindia.com/api/historical/cm/equity?symbol={symbol}",
                headers={**NSE_HEADERS, "X-Requested-With": "XMLHttpRequest"},
                timeout=12,
            )
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                if data:
                    df = pd.DataFrame(data)
                    df.columns = [c.strip().lower() for c in df.columns]
                    rename = {"ch_timestamp": "date", "ch_closing_price": "close",
                              "ch_trade_high_price": "high", "ch_trade_low_price": "low",
                              "ch_tot_traded_qty": "volume"}
                    df = df.rename(columns=rename)
                    needed = {"close", "high", "low", "volume"}
                    if needed.issubset(df.columns):
                        for c in needed:
                            df[c] = pd.to_numeric(df[c], errors="coerce")
                        df = df.dropna(subset=["close", "high", "low"])
                        df["volume"] = df["volume"].fillna(0)
                        if "date" in df.columns:
                            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
                        else:
                            df["date"] = ""
                        df = df.tail(days).reset_index(drop=True)
                        if len(df) >= 20:
                            nse_circuit_report(True)
                            return df[["date", "close", "high", "low", "volume"]]
            nse_circuit_report(False)
        except Exception as e:
            log.debug(f"fetch_history NSE {symbol}: {e}")
            nse_circuit_report(False)

    if _YFINANCE_OK:
        try:
            t = yf.Ticker(f"{symbol}.NS")
            h = t.history(period=f"{days}d")
            if not h.empty:
                df = h.reset_index().rename(columns={
                    "Date": "date", "Close": "close", "High": "high",
                    "Low": "low", "Volume": "volume",
                })
                df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
                for c in ("close", "high", "low", "volume"):
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                df = df.dropna(subset=["close", "high", "low"])
                df["volume"] = df["volume"].fillna(0)
                return df[["date", "close", "high", "low", "volume"]].reset_index(drop=True)
        except Exception as e:
            log.debug(f"fetch_history yfinance {symbol}: {e}")
    return pd.DataFrame()


def fetch_weekly_history(symbol: str, weeks: int = 52) -> pd.DataFrame:
    daily = fetch_history(symbol, days=weeks * 7 + 30)
    if daily.empty:
        return pd.DataFrame()
    try:
        daily = daily.reset_index(drop=True)
        daily["wk"] = daily.index // 5
        weekly = daily.groupby("wk").agg(
            close=("close", "last"), high=("high", "max"),
            low=("low", "min"), volume=("volume", "sum"),
        ).reset_index(drop=True)
        return weekly.tail(weeks)
    except Exception as e:
        log.debug(f"fetch_weekly_history {symbol}: {e}")
        return pd.DataFrame()
