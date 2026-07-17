"""
FORTRESS_UNIFIED — core/indicators.py
══════════════════════════════════════════════════════════════════════════════
Single indicator engine (ATR family incl. NATR normalisation, RSI-14, ADX-14,
MFI-14, moving averages, 52W hi/lo). Previously duplicated between sniper
and incubator with slightly different implementations — now one function,
one set of numbers, used everywhere including the ignition detector.
"""
from __future__ import annotations
import logging

import numpy as np
import pandas as pd

log = logging.getLogger("fortress.indicators")

_EMPTY = {k: 0.0 for k in [
    "atr14", "atr7", "atr20", "atr50", "atr100", "rsi14", "adx14", "mfi",
    "pdi", "ndi", "ma50", "ma200", "hi52", "lo52", "natr14", "natr100",
    "close_100", "box_high_20", "box_low_20",
]}


def compute_indicators(df: pd.DataFrame) -> dict:
    """
    Single fused indicator pass. NATR (normalised ATR = ATR / close-at-that-
    time) is used for all volatility-ratio comparisons so a stock that has
    multi-bagged doesn't get penalised for having a higher absolute ATR14
    than its ATR100 anchored at a lower price (PATCH-1 from sniper_v7,
    preserved here as the correct approach).
    """
    if df.empty or len(df) < 7:
        return dict(_EMPTY)
    try:
        h = df["high"].astype(float)
        l = df["low"].astype(float)
        c = df["close"].astype(float)
        v = (df["volume"].astype(float) if "volume" in df.columns
             else pd.Series(np.ones(len(df)), index=df.index))

        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)

        atr14_s = tr.ewm(span=14, adjust=False).mean()
        atr7 = float(tr.ewm(span=7, adjust=False).mean().iloc[-1]) if len(df) >= 7 else 0.0
        atr14 = float(atr14_s.iloc[-1]) if len(df) >= 14 else 0.0
        atr20 = float(tr.ewm(span=20, adjust=False).mean().iloc[-1]) if len(df) >= 20 else atr14
        atr50 = float(tr.ewm(span=50, adjust=False).mean().iloc[-1]) if len(df) >= 50 else atr14
        atr100 = float(tr.ewm(span=100, adjust=False).mean().iloc[-1]) if len(df) >= 100 else atr14

        delta = c.diff()
        gain = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi14 = float((100 - 100 / (1 + rs)).iloc[-1]) if not rs.isna().all() else 50.0

        pdm = h.diff().clip(lower=0)
        ndm = (-l.diff()).clip(lower=0)
        atr_adx = tr.ewm(span=14, adjust=False).mean()
        pdi = 100 * pdm.ewm(span=14, adjust=False).mean() / atr_adx.replace(0, np.nan)
        ndi = 100 * ndm.ewm(span=14, adjust=False).mean() / atr_adx.replace(0, np.nan)
        dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
        adx14 = float(dx.ewm(span=14, adjust=False).mean().iloc[-1]) if len(df) >= 14 else 0.0

        tp = (h + l + c) / 3
        mf = tp * v
        pos = mf.where(tp > tp.shift(), 0.0).rolling(14).sum()
        neg = mf.where(tp <= tp.shift(), 0.0).rolling(14).sum()
        mfi_v = float((100 - 100 / (1 + pos / neg.replace(0, np.nan))).iloc[-1]) if len(df) >= 14 else 50.0

        ma50 = float(c.rolling(50).mean().iloc[-1]) if len(df) >= 50 else 0.0
        ma200 = float(c.rolling(200).mean().iloc[-1]) if len(df) >= 200 else 0.0

        hi52 = float(h.tail(252).max()) if len(df) >= 252 else float(h.max())
        lo52 = float(l.tail(252).min()) if len(df) >= 252 else float(l.min())

        # box (20-bar) — used by the ignition detector for breakout checks.
        # CRITICAL: excludes today's bar. A breakout day's own high is by
        # definition part of "today", so including it in the box means a
        # breakout could never clear its own ceiling — this must be the
        # box structure as of yesterday's close, checked against today's bar.
        if len(df) >= 21:
            box_high_20 = float(h.iloc[-21:-1].max())
            box_low_20 = float(l.iloc[-21:-1].min())
        else:
            box_high_20 = float(h.iloc[:-1].max()) if len(df) > 1 else float(h.max())
            box_low_20 = float(l.iloc[:-1].min()) if len(df) > 1 else float(l.min())

        close_now = float(c.iloc[-1])
        close_100 = float(c.iloc[-100]) if len(df) >= 100 else close_now
        natr14 = atr14 / close_now if close_now > 0 else 0.0
        natr100 = atr100 / close_100 if close_100 > 0 else natr14

        return {
            "atr14": atr14, "atr7": atr7, "atr20": atr20, "atr50": atr50, "atr100": atr100,
            "rsi14": round(rsi14, 1), "adx14": round(adx14, 1), "mfi": round(mfi_v, 1),
            "pdi": round(float(pdi.iloc[-1]), 1), "ndi": round(float(ndi.iloc[-1]), 1),
            "ma50": round(ma50, 4), "ma200": round(ma200, 4),
            "hi52": round(hi52, 4), "lo52": round(lo52, 4),
            "natr14": round(natr14, 6), "natr100": round(natr100, 6),
            "close_100": round(close_100, 4),
            "box_high_20": round(box_high_20, 4), "box_low_20": round(box_low_20, 4),
        }
    except Exception as e:
        log.debug(f"compute_indicators: {e}")
        return dict(_EMPTY)
