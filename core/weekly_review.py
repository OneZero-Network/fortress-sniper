"""
FORTRESS_UNIFIED — core/weekly_review.py
══════════════════════════════════════════════════════════════════════════════
The Monday consolidated Claude review. This is the ONLY place Anthropic is
used in the pipeline, per your instruction — everything per-trade (Shariah,
insider narrative, pick enrichment) stays on OpenAI, untouched.

What it does:
  1. Pulls the last 7 days of: Sniper picks (SCREENER tab), Incubator pearls
     (INCUBATOR tab), ignition events (pearl_watchlist status changes),
     and resolved outcomes (outcomes table + DB_BACKUP/PERFORMANCE tabs).
  2. Builds a structured weekly digest — NOT raw dumps, so Claude reasons
     over a clean dataset rather than reparsing sheet formatting.
  3. Asks Claude for a genuine analysis: what worked, what the gate
     rejections are costing us, whether pearl-pedigree picks are
     outperforming cold-scan picks, and one concrete config.py tuning
     suggestion for the coming week.
  4. Posts the review to Telegram AND appends it to a WEEKLY_REVIEWS tab
     so it accumulates as its own training/reference archive over time.

This is a read-and-advise loop, not an auto-tune loop — it recommends,
you decide whether to apply the suggested config change.
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from . import config
from .sheets_client import read_sheet, append_row
from .telegram import send as send_telegram
from .db import get_conn

log = logging.getLogger("fortress.weekly_review")

try:
    from anthropic import Anthropic
    _client = Anthropic(api_key=config.ANTHROPIC_API_KEY) if config.ANTHROPIC_API_KEY else None
except ImportError:
    _client = None


def _rows_since(tab: str, days: int, date_col_idx: int = 0) -> list:
    """Read a sheet tab and filter to rows within the last `days`."""
    raw = read_sheet(tab)
    if not raw or len(raw) < 2:
        return []
    cutoff = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    header, body = raw[0], raw[1:]
    kept = [r for r in body if len(r) > date_col_idx and str(r[date_col_idx]) >= cutoff]
    return [header] + kept


def _pearl_pipeline_stats() -> dict:
    """Compare pearl-pedigree outcomes vs cold-scan outcomes from the
    outcomes table — the empirical answer to 'is the bridge working'."""
    try:
        with get_conn() as con:
            rows = con.execute(
                "SELECT pearl_pedigree, status, pnl_pct FROM outcomes "
                "WHERE status != 'open' AND exit_date > date('now', '-7 days')"
            ).fetchall()
        pearl = [r for r in rows if r[0]]
        cold = [r for r in rows if not r[0]]

        def _summ(rs):
            if not rs:
                return {"n": 0, "win_rate": None, "avg_pnl": None}
            wins = sum(1 for r in rs if "hit" in (r[1] or ""))
            avg_pnl = sum((r[2] or 0) for r in rs) / len(rs)
            return {"n": len(rs), "win_rate": round(wins / len(rs) * 100, 1),
                    "avg_pnl": round(avg_pnl, 2)}

        return {"pearl_pedigree": _summ(pearl), "cold_scan": _summ(cold)}
    except Exception as e:
        log.debug(f"_pearl_pipeline_stats: {e}")
        return {"pearl_pedigree": {"n": 0}, "cold_scan": {"n": 0}}


def build_weekly_digest() -> dict:
    """Assemble the structured week-in-review dataset Claude will reason over."""
    sniper_picks = _rows_since("SCREENER", 7)
    incubator_pearls = _rows_since("INCUBATOR", 7)
    rejects = _rows_since("REJECTS_LOG", 7)
    performance = _rows_since("PERFORMANCE", 7)
    pearl_stats = _pearl_pipeline_stats()

    def _gate_breakdown(rows: list) -> dict:
        if len(rows) < 2:
            return {}
        header = [h.lower() for h in rows[0]]
        if "gate" not in header:
            return {}
        idx = header.index("gate")
        counts: dict = {}
        for r in rows[1:]:
            if len(r) > idx:
                counts[r[idx]] = counts.get(r[idx], 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1])[:10])

    return {
        "week_ending": datetime.today().strftime("%Y-%m-%d"),
        "sniper_picks_count": max(0, len(sniper_picks) - 1),
        "incubator_pearls_count": max(0, len(incubator_pearls) - 1),
        "reject_gate_breakdown": _gate_breakdown(rejects),
        "performance_rows": max(0, len(performance) - 1),
        "pearl_vs_cold_scan": pearl_stats,
    }


def _ask_claude(digest: dict) -> Optional[str]:
    if _client is None:
        log.warning("Anthropic client unavailable — skipping weekly Claude review")
        return None

    prompt = f"""You are reviewing one week of output from FORTRESS_UNIFIED, an NSE India
equity screening pipeline with three stages: Incubator (weekly deep-value/insider
scanner that finds "pearls"), Sniper (daily technical scanner that detects when
pearls "ignite" plus scans the broader market), and Pine (chart-side execution).

Here is this week's structured data:
{json.dumps(digest, indent=2, default=str)}

Give a concise, honest analysis for a solo trader reviewing their own system:
1. What worked this week (be specific, cite numbers from the data — don't invent any).
2. Where the gates are rejecting the most candidates, and whether that
   rejection rate looks healthy or overly restrictive given the sample size.
3. Whether pearl-pedigree picks (Incubator thesis + Sniper ignition) are
   outperforming cold-scan picks so far — and explicitly say if the sample
   size is too small to conclude anything yet, rather than overclaiming.
4. ONE concrete, specific config.py tuning suggestion for next week
   (name the actual constant and a direction), with your reasoning.

Be direct and grounded in the numbers given. If the data is too sparse for
a claim, say so plainly rather than speculating. Keep it under 300 words."""

    try:
        resp = _client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if hasattr(b, "text"))
    except Exception as e:
        log.warning(f"Anthropic weekly review call failed: {e}")
        return None


def run_weekly_review() -> Optional[str]:
    """Entrypoint called by the Monday GHA workflow."""
    digest = build_weekly_digest()
    review_text = _ask_claude(digest)

    if review_text is None:
        review_text = (
            "⚠️ Claude review unavailable this week (no ANTHROPIC_API_KEY or "
            "API call failed). Raw digest:\n" + json.dumps(digest, indent=2, default=str)
        )

    header = f"🧠 <b>FORTRESS_UNIFIED — Weekly Review ({digest['week_ending']})</b>\n\n"
    send_telegram(header + review_text[:3500])

    try:
        append_row("WEEKLY_REVIEWS", [
            digest["week_ending"], json.dumps(digest, default=str), review_text,
        ])
    except Exception as e:
        log.warning(f"WEEKLY_REVIEWS append failed: {e}")

    return review_text


if __name__ == "__main__":
    import logging as _l
    _l.basicConfig(level=_l.INFO)
    print(run_weekly_review())
