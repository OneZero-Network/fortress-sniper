"""
FORTRESS_UNIFIED — core/order_flow.py
══════════════════════════════════════════════════════════════════════════════
Replaces sniper_daily's `_dummy_order_flow()` stub (which hardwired
whale_score=0 and was the root cause of the "0 passed all gates" first
live run — the confidence formula's std-penalty zeroed out every candidate
because one signal was always 0).

Two tiers:
  Tier 1 (NSE, circuit-breaker protected): delivery-to-traded %, the real
    institutional-accumulation signal. Skipped instantly once the circuit
    opens (GHA IPs are usually Akamai-blocked).
  Tier 2 (always available): volume-proxy whale detection from the daily
    history we already hold — vol surge on an up-close, no network needed.

VPOC upgrade vs legacy: the old Pine/sniper "VPOC" was actually a weekly
VWAP proxy. This computes a true volume point of control — a 24-bin
volume-at-price histogram over the last 60 sessions — from data already
in hand. delivery_pct = -1.0 means "unavailable", and downstream scoring
treats it as absent rather than zero.
"""
from __future__ import annotations
import logging
from typing import Dict

import numpy as np
import pandas as pd

from .nse_data import get_nse_session, NSE_HEADERS, nse_circuit_ok, nse_circuit_report

log = logging.getLogger("fortress.order_flow")


def _fetch_delivery_pct(symbol: str) -> float:
    """Tier 1: NSE trade_info delivery %. -1.0 on any failure."""
    if not nse_circuit_ok():
        return -1.0
    try:
        sess = get_nse_session()
        resp = sess.get(
            f"https://www.nseindia.com/api/quote-equity?symbol={symbol}&section=trade_info",
            headers={**NSE_HEADERS, "X-Requested-With": "XMLHttpRequest"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            dp = data.get("securityWiseDP", {}) or {}
            val = dp.get("deliveryToTradedQuantity")
            if val is not None:
                nse_circuit_report(True)
                return float(val)
        nse_circuit_report(False)
    except Exception as e:
        log.debug(f"delivery {symbol}: {e}")
        nse_circuit_report(False)
    return -1.0


def compute_vpoc(hist: pd.DataFrame, lookback: int = 60, bins: int = 24) -> float:
    """True volume point of control: the price level where the most volume
    traded over the lookback window."""
    if hist.empty or len(hist) < 10 or "volume" not in hist.columns:
        return 0.0
    try:
        tail = hist.tail(lookback)
        closes = tail["close"].astype(float).values
        vols = tail["volume"].astype(float).values
        mask = np.isfinite(closes) & np.isfinite(vols)
        closes, vols = closes[mask], vols[mask]
        if len(closes) < 10 or vols.sum() <= 0:
            return 0.0
        counts, edges = np.histogram(closes, bins=bins, weights=vols)
        idx = int(np.argmax(counts))
        return round(float((edges[idx] + edges[idx + 1]) / 2), 2)
    except Exception as e:
        log.debug(f"compute_vpoc: {e}")
        return 0.0


def compute_eod_order_flow(symbol: str, hist: pd.DataFrame, close: float,
                            try_nse: bool = True) -> Dict:
    """
    Returns the exact dict shape fortress_score() expects:
      whale_score, whale_flag, vol_ratio, vpoc, at_vpoc_support,
      delivery_pct (-1.0 = unavailable), whale_available (bool — whether
      any whale-quality signal exists; drives the confidence formula's
      signal-inclusion, see scoring.compute_confidence_score).
    """
    out = {"whale_score": 0.0, "whale_flag": False, "vol_ratio": 1.0,
           "vpoc": 0.0, "at_vpoc_support": False, "delivery_pct": -1.0,
           "whale_available": False}
    if hist.empty or len(hist) < 21 or close <= 0:
        return out

    try:
        vols = hist["volume"].astype(float)
        adv20 = float(vols.iloc[-21:-1].mean())
        vol_today = float(vols.iloc[-1])
        vol_ratio = vol_today / adv20 if adv20 > 0 else 1.0
        out["vol_ratio"] = round(vol_ratio, 2)

        closes = hist["close"].astype(float)
        up_close = len(closes) >= 2 and float(closes.iloc[-1]) > float(closes.iloc[-2])

        delivery = _fetch_delivery_pct(symbol) if try_nse else -1.0
        out["delivery_pct"] = round(delivery, 1)

        whale_score = 0.0
        whale_flag = False
        if delivery >= 0:
            out["whale_available"] = True
            if delivery >= 65 and vol_ratio >= 1.5:
                whale_score, whale_flag = 25.0, True
            elif delivery >= 50 and vol_ratio >= 1.2:
                whale_score, whale_flag = 15.0, True
            elif delivery >= 65:
                whale_score = 8.0
        else:
            # Tier 2 volume-proxy: no delivery data, infer accumulation
            # from surge-on-strength. Weaker signal, capped lower.
            if vol_ratio >= 1.8 and up_close:
                whale_score, whale_flag = 12.0, True
                out["whale_available"] = True
            elif vol_ratio >= 1.5 and up_close:
                whale_score = 6.0
                out["whale_available"] = True

        out["whale_score"] = whale_score
        out["whale_flag"] = whale_flag

        vpoc = compute_vpoc(hist)
        out["vpoc"] = vpoc
        if vpoc > 0:
            out["at_vpoc_support"] = (abs(close - vpoc) / close <= 0.03) and close >= vpoc * 0.99
    except Exception as e:
        log.debug(f"compute_eod_order_flow {symbol}: {e}")
    return out
