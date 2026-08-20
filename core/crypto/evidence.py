"""
FORTRESS_CRYPTO — core/crypto/evidence.py
══════════════════════════════════════════════════════════════════════════════
Single source of truth for how much trust each signal layer has actually
earned. This is the mechanism that prevents the Pearl Detection Machine
from quietly sliding back into "trust this score" — every layer's
maturity is declared HERE, in one place, and every Pearl output must
read from this file rather than assuming.

LEVELS:
  REJECTED   — proven not to work; NEVER contributes to Pearl scoring
  0          — Unvalidated; interesting observation only
  1          — Historically associated; some evidence, insufficient validation
  2          — Validated signal; survives out-of-sample testing
  3          — Live validated; demonstrated through sufficient real-time observation

PROMOTION RULE: a layer's level only changes when a specific research
result justifies it, and that change happens HERE, with a comment
explaining why — never silently, never based on a single good-looking
run. As of this file's creation, every scoring layer is at Level 0. That
is the honest current state, not a placeholder to be embarrassed about.
"""
from __future__ import annotations

REJECTED = -1

LEVEL_LABELS = {
    REJECTED: "REJECTED",
    0: "Level 0 — Unvalidated",
    1: "Level 1 — Historically associated",
    2: "Level 2 — Validated signal",
    3: "Level 3 — Live validated",
}

EVIDENCE = {
    "technical_core": {
        "level": REJECTED,
        "detail": ("Regime Audit v1 + V5 falsification test: -74.19% compounded validation "
                    "return, apparent edge carried by 5 outlier trades (removing them flips it "
                    "negative), regime classifier wrong 63.6-100% of the time. Formally rejected "
                    "for deployment — never contributes to Pearl scoring."),
    },
    "regime_v1": {
        "level": REJECTED,
        "detail": ("BULL/NORMAL_VOL calls followed by BTC actually rising only 0% (discovery) / "
                    "36.4% (validation) of the time. Quarantined — research-only, logged but "
                    "never scored."),
    },
    "regime_v2": {
        "level": 0,
        "detail": ("Descriptive rebuild with breadth/momentum/liquidity factors, calibration "
                    "test built and runnable (scripts/calibrate_regime_v2.py) but has not yet "
                    "cleared a trust bar on real data. Not used for Pearl scoring."),
    },
    "whale": {
        "level": 0,
        "detail": ("W1 observation logger (scripts/experiment_w1_n1_observe.py) is accumulating "
                    "real forward-return data daily. Not yet enough resolved observations to "
                    "claim predictive value — used in Pearl discovery as a DESCRIPTIVE signal "
                    "('something unusual is happening'), not a validated predictor."),
    },
    "news": {
        "level": 0,
        "detail": ("N1 observation logger running alongside W1, same status — descriptive "
                    "signal only, not yet validated."),
    },
    "false_pearl": {
        "level": 0,
        "detail": ("F1 cross-sectional test (scripts/experiment_f1_false_pearl.py) came back "
                    "inconclusive on a top-40 universe (no clean risk/return pattern, zero "
                    "HIGH_RISK coins in that universe). The underlying contract-security checks "
                    "(mint authority, honeypot, tax, LP lock) are independently sourced facts "
                    "about the contract, not a statistical prediction — used as a FILTER against "
                    "known-bad contract properties, not claimed as a validated forecaster."),
    },
    "liquidity_structure": {
        "level": 0,
        "detail": ("Volume/market-cap ratio and price momentum are used as DESCRIPTIVE market-"
                    "structure observations ('is this liquid, is something moving'), explicitly "
                    "not as the rejected technical-trigger's predictive claim."),
    },
}


def overall_evidence_level() -> dict:
    """The Pearl Score's overall evidence level is the MINIMUM level
    among the layers actually contributing to it (technical_core and
    regime_v1 are REJECTED and never contribute, so they're excluded
    from this calculation entirely — the Pearl Score doesn't touch them
    at all, not even at low weight)."""
    contributing = ["whale", "news", "false_pearl", "liquidity_structure"]
    levels = [EVIDENCE[k]["level"] for k in contributing]
    min_level = min(levels)
    return {"level": min_level, "label": LEVEL_LABELS[min_level],
            "contributing_layers": contributing}
