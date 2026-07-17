"""
FORTRESS_UNIFIED — core/target_intel.py
══════════════════════════════════════════════════════════════════════════════
The "heist" — per-symbol NSE intelligence: corporate announcements
(catalyst detection), insider/PIT buys, SAST deals, pledge %, plus the
market-level FII/DII flows. All calls share the NSE circuit breaker, so on
a GHA runner where Akamai blocks the API, the entire module degrades to
instant neutral responses instead of burning 400 × timeout.

Heist placement (fixing the v8.2 regression): called ONLY for
  (a) the pearl watchlist (small N, always worth full intel), and
  (b) cold-scan survivors AFTER the math gates
— never for the whole 400-candidate universe.

Also fixes the legacy crash point: fetch_fii_dii is fully wrapped and
returns neutral 15 on any failure; nothing here can raise into run().
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta
from typing import Dict

from . import config
from .nse_data import get_nse_session, NSE_HEADERS, nse_circuit_ok, nse_circuit_report

log = logging.getLogger("fortress.intel")

_HDRS = {**NSE_HEADERS, "X-Requested-With": "XMLHttpRequest",
         "Accept": "application/json, text/plain, */*"}

NEUTRAL_INTEL = {"catalyst": False, "catalyst_headline": "",
                 "insider_count": 0, "insider_total_cr": 0.0,
                 "sast_count": 0, "pledge_pct": -1.0, "intel_source": "SKIPPED"}


def _get_json(url: str, timeout: int = 10):
    if not nse_circuit_ok():
        return None
    try:
        resp = get_nse_session().get(url, headers=_HDRS, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            nse_circuit_report(True)
            return data
        nse_circuit_report(False)
    except Exception as e:
        log.debug(f"_get_json {url[:60]}: {e}")
        nse_circuit_report(False)
    return None


def fetch_target_intel(symbol: str) -> Dict:
    """Full per-symbol intel. Every sub-fetch degrades independently."""
    out = dict(NEUTRAL_INTEL)
    if not nse_circuit_ok():
        return out
    out["intel_source"] = "NSE"
    cutoff = datetime.today() - timedelta(days=config.INTEL_LOOKBACK_DAYS)

    # ── Announcements → catalyst keywords ────────────────────────────────
    data = _get_json("https://www.nseindia.com/api/corporate-announcements"
                     f"?index=equities&symbol={symbol}")
    if isinstance(data, list):
        for item in data[:25]:
            desc = str(item.get("desc", "")) + " " + str(item.get("attchmntText", ""))
            desc_u = desc.upper()
            if any(kw in desc_u for kw in config.CATALYST_KEYWORDS):
                out["catalyst"] = True
                out["catalyst_headline"] = desc.strip()[:120]
                break

    # ── Insider (PIT) buys ───────────────────────────────────────────────
    data = _get_json("https://www.nseindia.com/api/corporates-pit"
                     f"?index=equities&symbol={symbol}")
    if isinstance(data, dict):
        total_val, count = 0.0, 0
        for row in data.get("data", [])[:60]:
            try:
                if "ACQUISITION" not in str(row.get("acqMode", "")).upper() and \
                   "BUY" not in str(row.get("tdpTransactionType", "")).upper():
                    continue
                val = float(str(row.get("secVal", "0")).replace(",", "") or 0)
                d = str(row.get("date", row.get("intimDate", "")))[:11]
                try:
                    if datetime.strptime(d.strip(), "%d-%b-%Y") < cutoff:
                        continue
                except ValueError:
                    pass
                total_val += val
                count += 1
            except Exception:
                continue
        out["insider_count"] = count
        out["insider_total_cr"] = round(total_val / 1e7, 2)

    # ── SAST deals ───────────────────────────────────────────────────────
    data = _get_json("https://www.nseindia.com/api/corporate-sast"
                     f"?index=equities&symbol={symbol}")
    if isinstance(data, dict):
        out["sast_count"] = len(data.get("data", []) or [])

    # ── Pledge % (affirmative data only; -1.0 = unknown, never blocks) ───
    data = _get_json("https://www.nseindia.com/api/corporate-share-holdings-master"
                     f"?index=equities&symbol={symbol}")
    if isinstance(data, list) and data:
        try:
            latest = data[0]
            pl = latest.get("pledgePercent", latest.get("pledgedPercentage"))
            if pl is not None:
                out["pledge_pct"] = float(pl)
        except Exception:
            pass
    return out


def pledge_gate_ok(pledge_pct: float) -> bool:
    """Blocks only on affirmatively bad data — unknown (-1) passes."""
    if not config.PLEDGE_GATE_ENABLED or pledge_pct < 0:
        return True
    return pledge_pct <= config.PLEDGE_GATE_MAX_PCT


def fetch_fii_dii() -> Dict:
    """Market-level FII/DII net flows → 0-30 score (15 = neutral).
    NEVER raises (the legacy version outside try/except killed whole runs)."""
    out = {"fii_score": 15, "fii_net_cr": 0.0, "dii_net_cr": 0.0, "source": "NEUTRAL"}
    try:
        data = _get_json("https://www.nseindia.com/api/fiidiiTradeReact", timeout=10)
        if isinstance(data, list):
            for row in data:
                cat = str(row.get("category", "")).upper()
                net = float(str(row.get("netValue", "0")).replace(",", "") or 0)
                if "FII" in cat or "FPI" in cat:
                    out["fii_net_cr"] = net
                elif "DII" in cat:
                    out["dii_net_cr"] = net
            net = out["fii_net_cr"]
            out["fii_score"] = (28 if net > 2000 else 22 if net > 500 else
                                 18 if net > 0 else 10 if net > -1000 else 5)
            out["source"] = "NSE"
    except Exception as e:
        log.debug(f"fetch_fii_dii: {e}")
    return out
