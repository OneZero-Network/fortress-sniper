"""
FORTRESS_UNIFIED — core/fundamentals.py
══════════════════════════════════════════════════════════════════════════════
Incubator's fundamental gates, ported to a GHA-friendly data source
(yfinance quarterly statements — proven working on your runner, unlike
NSE's blocked APIs), plus the company-profile fetch that finally grounds
the Shariah L3 LLM audit in real business descriptions instead of
industry="UNKNOWN" (which your first live run's ~24 blind OpenAI calls
exposed).

EPS gate semantics (NaN-safe, data-gap-safe):
  - data unavailable → PASS with 0 bonus + 'NO_EPS_DATA' flag
    (never punish a data gap; punish only affirmative bad numbers)
  - earnings shrinking (latest growth < 0, no acceleration) → HARD REJECT
    ('EPS_FAIL', matching your legacy REJECTS_LOG vocabulary)
  - growing but decelerating → PASS, small bonus
  - accelerating ≥ EPS_ACCEL_PCT_MIN → PASS, full bonus
  - base-effect guard: |prior value| < threshold → treated as no-data
    (a paise-level prior EPS makes growth % meaningless)
"""
from __future__ import annotations
import logging
import math
from typing import Dict

log = logging.getLogger("fortress.fundamentals")

try:
    import yfinance as yf
    _YF = True
except ImportError:
    _YF = False

_PROFILE_CACHE: Dict[str, Dict] = {}
_FIN_CACHE: Dict[str, object] = {}


def _finite(x) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def get_company_profile(symbol: str) -> Dict:
    """{name, sector, industry, summary} from yfinance .info, cached.
    Empty-string fields on any failure — callers must handle absence."""
    sym = symbol.upper()
    if sym in _PROFILE_CACHE:
        return _PROFILE_CACHE[sym]
    out = {"name": "", "sector": "", "industry": "", "summary": ""}
    if _YF:
        try:
            info = yf.Ticker(f"{sym}.NS").info or {}
            out = {
                "name": str(info.get("longName", info.get("shortName", "")) or ""),
                "sector": str(info.get("sector", "") or ""),
                "industry": str(info.get("industry", "") or ""),
                "summary": str(info.get("longBusinessSummary", "") or "")[:500],
            }
        except Exception as e:
            log.debug(f"profile {sym}: {e}")
    _PROFILE_CACHE[sym] = out
    return out


def _quarterly_series(symbol: str, statement: str, row_names: list):
    """First matching row from a quarterly statement, newest-first values."""
    sym = symbol.upper()
    key = f"{sym}:{statement}"
    if key not in _FIN_CACHE:
        df = None
        if _YF:
            try:
                t = yf.Ticker(f"{sym}.NS")
                df = getattr(t, statement, None)
            except Exception as e:
                log.debug(f"{statement} {sym}: {e}")
        _FIN_CACHE[key] = df
    df = _FIN_CACHE[key]
    if df is None or getattr(df, "empty", True):
        return None
    for rn in row_names:
        if rn in df.index:
            s = df.loc[rn].dropna()
            if len(s):
                try:
                    return s.sort_index(ascending=False).astype(float)
                except Exception:
                    return None
    return None


def debt_and_quality_ratios(symbol: str) -> Dict:
    """
    Pulls the ratios needed for (a) the quantitative Shariah debt screen
    and (b) the Value/Quality factor Z-scores:
      - debt_to_equity   : total debt / total equity (balance sheet)
      - debt_to_assets   : total debt / total assets (AAOIFI-style leg)
      - pe_ratio         : trailing P/E (value factor)
      - pb_ratio         : price/book (value factor, backup)
      - roe_pct          : return on equity % (quality factor)
    All fields default to None (not 0) when unavailable — callers must
    treat None as "no data", never as "zero debt" or "zero P/E".
    """
    sym = symbol.upper()
    out = {"debt_to_equity": None, "debt_to_assets": None,
           "pe_ratio": None, "pb_ratio": None, "roe_pct": None,
           "total_debt_cr": None, "market_cap_cr": None}
    if not _YF:
        return out
    try:
        t = yf.Ticker(f"{sym}.NS")
        info = t.info or {}

        pe = info.get("trailingPE", info.get("forwardPE"))
        if _finite(pe) and pe is not None and pe > 0:
            out["pe_ratio"] = round(float(pe), 2)

        pb = info.get("priceToBook")
        if _finite(pb) and pb is not None and pb > 0:
            out["pb_ratio"] = round(float(pb), 2)

        roe = info.get("returnOnEquity")
        if _finite(roe) and roe is not None:
            out["roe_pct"] = round(float(roe) * 100, 2)

        de = info.get("debtToEquity")  # yfinance reports this as a % already (e.g. 45.2 = 0.452)
        if _finite(de) and de is not None:
            out["debt_to_equity"] = round(float(de) / 100, 4)

        mcap = info.get("marketCap")
        if _finite(mcap) and mcap:
            out["market_cap_cr"] = round(float(mcap) / 1e7, 1)

        # Balance-sheet fallback / cross-check for debt-to-assets
        bs = getattr(t, "quarterly_balance_sheet", None)
        if bs is not None and not bs.empty:
            def _row(names):
                for n in names:
                    if n in bs.index:
                        s = bs.loc[n].dropna()
                        if len(s):
                            return float(s.iloc[0])
                return None

            total_debt = _row(["Total Debt", "Long Term Debt", "Net Debt"])
            total_assets = _row(["Total Assets"])
            total_equity = _row(["Stockholders Equity", "Common Stock Equity"])

            if total_debt is not None and _finite(total_debt):
                out["total_debt_cr"] = round(total_debt / 1e7, 1)
                if total_assets and _finite(total_assets) and total_assets > 0:
                    out["debt_to_assets"] = round(total_debt / total_assets, 4)
                if out["debt_to_equity"] is None and total_equity and _finite(total_equity) and total_equity > 0:
                    out["debt_to_equity"] = round(total_debt / total_equity, 4)
    except Exception as e:
        log.debug(f"debt_and_quality_ratios {sym}: {e}")
    return out


def eps_acceleration(symbol: str) -> Dict:
    """See module docstring for gate semantics."""
    out = {"available": False, "accel": False, "g1": 0.0, "g2": 0.0,
           "score": 0, "reject": False, "flag": "NO_EPS_DATA"}
    ser = _quarterly_series(symbol, "quarterly_income_stmt",
                             ["Diluted EPS", "Basic EPS"])
    base_floor = 1.0
    if ser is None:
        ser = _quarterly_series(symbol, "quarterly_income_stmt",
                                 ["Net Income", "Net Income Common Stockholders"])
        base_floor = 1e7  # ₹1 Cr when falling back to net income
    if ser is None or len(ser) < 3:
        return out

    v0, v1, v2 = float(ser.iloc[0]), float(ser.iloc[1]), float(ser.iloc[2])
    if not all(_finite(v) for v in (v0, v1, v2)):
        return out
    if abs(v1) < base_floor or abs(v2) < base_floor:
        out["flag"] = "BASE_EFFECT"
        return out

    g1 = (v0 - v1) / abs(v1)
    g2 = (v1 - v2) / abs(v2)
    if not (_finite(g1) and _finite(g2)):
        return out

    out.update(available=True, g1=round(g1 * 100, 1), g2=round(g2 * 100, 1), flag="")
    from . import config
    if g1 > g2 and g1 >= config.EPS_ACCEL_PCT_MIN:
        out.update(accel=True, score=25, flag="EPS_ACCEL")
    elif g1 > 0:
        out.update(score=10, flag="EPS_GROWING")
    else:
        out.update(reject=True, flag="EPS_SHRINKING")
    return out


def revenue_quality(symbol: str) -> Dict:
    """Bonus-only quality check: YoY revenue growth + OCF/NI conversion.
    Never rejects — flags feed quality_flags on the pearl."""
    out = {"score": 0, "flags": []}
    try:
        rev = _quarterly_series(symbol, "quarterly_income_stmt",
                                 ["Total Revenue", "Operating Revenue"])
        if rev is not None and len(rev) >= 5:
            yoy = (float(rev.iloc[0]) - float(rev.iloc[4])) / abs(float(rev.iloc[4]))
            if _finite(yoy):
                if yoy > 0.10:
                    out["score"] += 8
                    out["flags"].append("REV_YOY+")
                elif yoy < 0:
                    out["flags"].append("REV_SHRINK")

        ocf = _quarterly_series(symbol, "quarterly_cashflow",
                                 ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"])
        ni = _quarterly_series(symbol, "quarterly_income_stmt",
                                ["Net Income", "Net Income Common Stockholders"])
        if ocf is not None and ni is not None and len(ocf) >= 4 and len(ni) >= 4:
            ocf_ttm = float(ocf.iloc[:4].sum())
            ni_ttm = float(ni.iloc[:4].sum())
            if ni_ttm > 0 and _finite(ocf_ttm):
                from . import config
                ratio = ocf_ttm / ni_ttm
                if ratio >= config.QUALITY_OCF_PAT_MIN:
                    out["score"] += 7
                    out["flags"].append("OCF_CLEAN")
                elif ratio < 0.3:
                    out["flags"].append("LOW_OCF")
    except Exception as e:
        log.debug(f"revenue_quality {symbol}: {e}")
    return out
