
    risk_pct_equity = ACCOUNT_RISK_PCT
    risk_per_sh     = max(close - stop_loss, close * 0.02)
    risk_rupees     = ACCOUNT_EQUITY * risk_pct_equity

    shares_vol   = math.floor(risk_rupees / risk_per_sh) if risk_per_sh > 0 else 0
    score_factor = (composite / 100.0) ** 0.5
    shares_blend = math.floor(shares_vol * (0.5 + 0.5 * score_factor))

    if composite >= GRADE_APEX:     deploy = 1.00
    elif composite >= GRADE_PRISTINE: deploy = 0.75
    elif composite >= GRADE_GOOD:   deploy = 0.50
    elif composite >= GRADE_PROBE:  deploy = 0.25
    else:                           deploy = 0.0

    shares_final = math.floor(shares_blend * deploy)
    max_shares   = math.floor((ACCOUNT_EQUITY * 0.10) / close) if close > 0 else 0
    shares_final = min(shares_final, max_shares)
    pos_value    = shares_final * close
    risk_actual  = shares_final * risk_per_sh / ACCOUNT_EQUITY * 100 if ACCOUNT_EQUITY > 0 else 0

    pos_label = (f"{shares_final} sh × ₹{close:.2f} = ₹{pos_value:,.0f} | "
                 f"Risk ₹{shares_final*risk_per_sh:,.0f} ({risk_actual:.1f}%)"
                 if shares_final > 0 else "— (below sizing min)")

    return {"shares": shares_final, "pos_value": round(pos_value), "deploy_pct": round(deploy * 100),
            "risk_actual_pct": round(risk_actual, 2), "pos_label": pos_label}


def calc_exit_plan(close: float, atr14: float, sector: str) -> dict:
    """3-Target graduated exit."""
    atr_mult = SECTOR_ATR_MULT.get(sector, 1.0)
    risk     = atr14 * 2.0 * atr_mult if atr14 > 0 else close * 0.03

    r1 = round(close + risk * 2.5, 2)
    r2 = round(close + risk * 4.0, 2)
    r3 = round(close + risk * 6.5, 2)
    trail_trigger = r2
    trail_stop    = round(r2 - atr14 * 2.5 * atr_mult, 2)

    r1_pct = round((r1 - close) / close * 100, 1)
    r2_pct = round((r2 - close) / close * 100, 1)
    r3_pct = round((r3 - close) / close * 100, 1)

    return {
        "r1": r1, "r2": r2, "r3": r3,
        "r1_pct": r1_pct, "r2_pct": r2_pct, "r3_pct": r3_pct,
        "trail_trigger": trail_trigger, "trail_stop": trail_stop,
        "sell_pct_r1": 30, "sell_pct_r2": 30, "sell_pct_r3": 40,
    }


# ══════════════════════════════════════════════════════════════════════════
# SECTION 13 — APEX COMPOSITE SCORING ENGINE (FIXED)
# ══════════════════════════════════════════════════════════════════════════

# FIX APEX-CRIT-02: Earnings veto at GATE 0
def score_symbol(sym: str, hist: pd.DataFrame, close: float,
                 turnover_lakhs: float, macro: dict,
                 fii_data: dict) -> Optional[dict]:
    """Master scoring function. Earnings veto at GATE 0."""

    # ── GATE 0: Earnings veto (cheap, do first) ────────────────────────
    earnings_days = _check_earnings(sym)
    if earnings_days is not None and 0 <= earnings_days <= 3:
        log.warning(f"{sym}: EARNINGS VETO ({earnings_days}d) — skipped before scoring")
        return None

    # ── Hard gates ──────────────────────────────────────────────────────
    if not is_halal(sym):
        return None

    sector = get_sector(sym)
    if sector in SECTOR_BLOCKED:
        return None

    if len(hist) < 30:
        return None

    if turnover_lakhs < MIN_TURNOVER_LAKHS:
        return None

    macro_state = macro.get("macro_state", "CHOP")
    if macro_state == "MASSACRE":
        return None

    # ── Indicators ──────────────────────────────────────────────────────
    atr_series = _atr(hist, 14)
    atr14      = float(atr_series.iloc[-1]) if not atr_series.empty else 0.0
    if atr14 <= 0:
        return None

    sector_atr_mult = SECTOR_ATR_MULT.get(sector, 1.0)
    atr14_adj       = atr14 * sector_atr_mult

    rsi_v = float(_rsi(hist["close"]).iloc[-1])
    mfi_v = _mfi(hist)
    adx_v = _adx(hist)
    adv20 = float(hist["volume"].tail(20).mean())

    ma200 = float(hist["close"].tail(200).mean()) if len(hist) >= 200 else float(hist["close"].mean())
    alt_pct = (close - ma200) / ma200 * 100 if ma200 > 0 else 0

    if alt_pct < -5.0:
        return None

    # ── Volume Profile ───────────────────────────────────────────────────
    profile    = _vpoc(hist)
    poc        = profile.get("poc", 0.0)

    # ── Stop Loss ─────────────────────────────────────────────────────────
    stop_from_atr = close - 2.5 * atr14_adj
    stop_from_poc = poc * 0.97 if poc > 0 else stop_from_atr
    stop_loss     = round(max(min(stop_from_atr, stop_from_poc), close * 0.88), 2)
    risk_pct      = round((close - stop_loss) / close * 100, 1)

    # ── Sub-engine scores ───────────────────────────────────────────────
    vpoc_score, vpoc_layers = calc_fortress_vpoc_score(
        hist, close, atr14, adv20, poc, ma200, sector
    )

    whale_score, whale_detail = calc_whale_radar(hist, adv20)

    div_score, div_detail = calc_divergence(hist)

    vp_score, vp_label = calc_vol_profile_score(profile, close)

    pat_score, pat_label = calc_pattern_score(hist, atr14, profile)

    mc = calc_monte_carlo(hist, stop_loss, close)
    mc_survival = mc.get("survival")

    # FIX APEX-CRIT-03: De-duplicated Bayesian (whale merged, VPOC merged)
    bayes = calc_bayesian_apex(
        macro_state   = macro_state,
        breadth_ok    = macro.get("breadth_ok", True),
        layer1        = vpoc_layers["layer1"],
        layer2        = vpoc_layers["layer2"],
        layer3        = vpoc_layers["layer3"],
        whale_detected= whale_detail["whale_detected"] or whale_detail["stealth_score"] >= 50,
        div_type      = div_detail["div_type"],
        vol_profile_score = vp_score,
        mfi_v         = mfi_v,
        adx_v         = adx_v,
        alt_pct       = alt_pct,
        mc_survival   = mc_survival,
    )

    # ── APEX COMPOSITE ───────────────────────────────────────────────────
    mc_score = mc_survival if mc_survival is not None else 50.0
    bayes_score = float(bayes["bayes_pct"])

    raw_composite = (
        vpoc_score  * W["fortress_vpoc"] +
        whale_score * W["whale_radar"]   +
        div_score   * W["divergence"]    +
        vp_score    * W["vol_profile"]   +
        pat_score   * W["pattern"]       +
        bayes_score * W["bayesian"]
    )

    macro_damp = {"CLEAR": 1.0, "CHOP": 0.88, "PANIC": 0.60, "MASSACRE": 0.0}
    composite  = round(raw_composite * macro_damp.get(macro_state, 0.88))
    composite  = min(100, max(0, composite))

    if whale_detail["signal_type"] == "STEALTH" and vpoc_layers["all_layers"]:
        composite = min(100, composite + 8)

    if bayes["bayes_pct"] >= 70:
        composite = min(100, composite + 5)

    if composite < APEX_MIN_SCORE:
        return None

    # ── Grade ─────────────────────────────────────────────────────────
    if composite >= GRADE_APEX:
        grade, grade_icon = "⚔️ APEX",    "⚔️"
    elif composite >= GRADE_PRISTINE:
        grade, grade_icon = "💎 PRISTINE", "💎"
    elif composite >= GRADE_GOOD:
        grade, grade_icon = "🟢 GOOD",     "🟢"
    elif composite >= GRADE_PROBE:
        grade, grade_icon = "🔵 PROBE",    "🔵"
    else:
        return None

    # ── Exit plan & position ────────────────────────────────────────────
    exits    = calc_exit_plan(close, atr14_adj, sector)
    position = calc_position(close, stop_loss, composite)

    # ── Story ───────────────────────────────────────────────────────────────
    story_parts = []
    if whale_detail["whale_detected"]:
        story_parts.append(whale_detail["whale_label"].split("|")[0].strip()[:60])
    if vpoc_layers["layer1"]:
        story_parts.append(f"Price AT institutional POC (₹{poc:.2f})")
    if div_detail["div_type"] == "BULLISH_HIDDEN":
        story_parts.append("Hidden RSI divergence — smart money dip-buying")
    if "Cup" in pat_label or "VCP" in pat_label:
        story_parts.append(f"Pattern: {pat_label[:50]}")
    if bayes["bayes_pct"] >= 65:
        story_parts.append(f"11-node Bayes: {bayes['bayes_pct']}% conviction")
    if not story_parts:
        story_parts.append(f"APEX score {composite}/100 — composite setup")
    story = "; ".join(story_parts[:3])

    return {
        "symbol":    sym,
        "sector":    sector,
        "close":     round(close, 2),
        "composite": composite,
        "grade":     grade,
        "grade_icon": grade_icon,

        "stop_loss":  stop_loss,
        "risk_pct":   risk_pct,
        "buy_lo":     round(close * 0.99, 2),
        "buy_hi":     round(close * 1.01, 2),

        "r1": exits["r1"], "r2": exits["r2"], "r3": exits["r3"],
        "r1_pct": exits["r1_pct"], "r2_pct": exits["r2_pct"], "r3_pct": exits["r3_pct"],
        "sell_r1": exits["sell_pct_r1"], "sell_r2": exits["sell_pct_r2"], "sell_r3": exits["sell_pct_r3"],
        "trail_stop": exits["trail_stop"],

        "shares":       position["shares"],
        "pos_value":    position["pos_value"],
        "deploy_pct":   position["deploy_pct"],
        "pos_label":    position["pos_label"],

        "vpoc_score":  round(vpoc_score, 1),
        "whale_score": round(whale_score, 1),
        "div_score":   round(div_score, 1),
        "vp_score":    round(vp_score, 1),
        "pat_score":   round(pat_score, 1),
        "bayes_pct":   bayes["bayes_pct"],
        "mc_survival": mc_survival,

        "whale_label":  whale_detail["whale_label"],
        "pat_label":    pat_label,
        "div_label":    div_detail["div_label"],
        "div_detail":   div_detail,
        "vp_label":     vp_label,
        "mc_label":     mc["label"],
        "bayes_label":  bayes["bayes_label"],
        "vpoc_layers":  vpoc_layers,

        "rsi":    round(rsi_v, 1),
        "mfi":    round(mfi_v, 1),
        "adx":    round(adx_v, 1),
        "atr14":  round(atr14, 2),
        "poc":    round(poc, 2),
        "ma200":  round(ma200, 2),
        "alt_pct": round(alt_pct, 1),
        "adv20":   round(adv20, 0),
        "turnover_lakhs": round(turnover_lakhs, 1),
        "whale_signal": whale_detail["signal_type"],

        "story":         story,
        "earnings_days": earnings_days,

        "days_to_r1_est": mc.get("days_to_t1") or SWING_HORIZON_DAYS,
        "r1_hit_prob":    mc.get("t1_hit_pct", 0),
    }


# FIX APEX-CRIT-02: Returns nearest future date, not first parsed
def _check_earnings(sym: str) -> Optional[int]:
    """Best-effort earnings proximity check via yfinance. Returns nearest future date."""
    try:
        import yfinance as yf
        t   = yf.Ticker(f"{sym}.NS")
        cal = t.calendar
        if cal is None:
            return None
        dates = cal.get("Earnings Date", []) if isinstance(cal, dict) else []
        if hasattr(cal, "T"):
            try:
                dates = cal.T.get("Earnings Date", [])
            except Exception:
                pass
        today = datetime.today()
        future_days = []
        for d in (dates if hasattr(dates, "__iter__") else [dates]):
            try:
                dt = pd.to_datetime(d).to_pydatetime()
                days = (dt - today).days
                if days >= 0:
                    future_days.append(days)
            except Exception:
                pass
        return min(future_days) if future_days else None
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════
# SECTION 14 — TELEGRAM FORMATTER (CLEAN FORMAT)
# ══════════════════════════════════════════════════════════════════════════

def format_pick_telegram_clean(r: dict, rank: int) -> str:
    """Clean Telegram format per user specification."""
    sym   = r["symbol"]
    price = r["close"]
    buy   = r["buy_hi"]  # Use upper bound of buy zone
    sell  = r["r1"]      # First target
    sl    = r["stop_loss"]
    days  = r["days_to_r1_est"]
    story = r["story"]
    grade = r["grade"]

    lines = [
        f"{grade} #{rank} — {sym} (₹{price:.2f})",
        f"",
        f"Buy @ ₹{buy:.2f}",
        f"Sell @ ₹{sell:.2f} (+{r['r1_pct']}%)",
        f"SL @ ₹{sl:.2f} (Risk {r['risk_pct']}%)",
        f"",
        f"Will achieve in ~{days} days",
        f"",
        f"Why to buy: {story}",
    ]
    return "
".join(lines)


def format_header_telegram(n: int, date_label: str, macro: dict, data_source: str) -> str:
    macro_state = macro.get("macro_state", "CHOP")
    vix         = macro.get("vix_val", 18.0)
    icon        = {"CLEAR":"✅","CHOP":"⚠️","PANIC":"🔴","MASSACRE":"💀"}.get(macro_state, "❓")
    return (
        f"⚔️ APEX SNIPER v1.2 — HALAL SWING PICKS
"
        f"📅 {date_label} | {icon} {macro_state} | VIX {vix:.1f}
"
        f"💎 {n} Premium Setup(s)
"
        f"{'─' * 30}"
    )


def format_footer_telegram(count: int, screened: int) -> str:
    return (
        f"
{'─' * 30}
"
        f"🔎 Screened {screened} halal candidates → {count} picks
"
        f"⚖️ Shariah compliant | 10-15 day swing | Risk 1.5% per trade
"
        f"🤲 Bismillah — trade with discipline and tawakkul"
    )


def _send_telegram(token: str, chat_id: str, text: str):
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in _split_msg(text):
        try:
            r = requests.post(url, json={"chat_id": chat_id, "text": chunk,
                                          "parse_mode": ""}, timeout=20)  # Plain text, no MarkdownV2
            if not r.ok:
                log.warning(f"Telegram {r.status_code}: {r.text[:200]}")
        except Exception as e:
            log.warning(f"Telegram error: {e}")


def _split_msg(msg: str, limit: int = 4000) -> List[str]:
    """Split long message at line boundaries."""
    if len(msg) <= limit:
        return [msg]
    parts = []
    while msg:
        if len(msg) <= limit:
            parts.append(msg); break
        cut = limit
        for i in range(min(100, cut), 0, -1):
            if msg[cut - i] == "
":
                cut = cut - i; break
        parts.append(msg[:cut])
        msg = msg[cut:].lstrip("
")
    return parts


def send_all_telegram(messages: List[str]):
    targets = [TELEGRAM_CHAT_ID] + TELEGRAM_SHARE_IDS
    for cid in targets:
        if not cid:
            continue
        for msg in messages:
            _send_telegram(TELEGRAM_TOKEN, cid, msg)
            time.sleep(0.4)


# ══════════════════════════════════════════════════════════════════════════
# SECTION 15 — PERSISTENCE (FIXED)
# ══════════════════════════════════════════════════════════════════════════

# FIX APEX-HIGH-05: save_results properly defined
def save_results(picks: List[dict], run_date: str):
    if not picks:
        return
    try:
        conn = sqlite3.connect(DB_PATH)
        for r in picks:
            conn.execute("""
                INSERT OR IGNORE INTO apex_results
                (run_date, symbol, grade, composite_score, close, stop_loss, t1, t2, t3, story)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (run_date, r["symbol"], r["grade"], r["composite"],
                  r["close"], r["stop_loss"], r["r1"], r["r2"], r["r3"], r["story"]))
        conn.commit()
        conn.close()
        log.info(f"Persisted {len(picks)} picks to DB")
    except Exception as e:
        log.error(f"DB save failed: {e}")


# ══════════════════════════════════════════════════════════════════════════
# SECTION 16 — MAIN ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════

def run_apex_sniper() -> List[dict]:
    """Main entry point. Full pipeline."""
    _init_db()
    date_label = datetime.today().strftime("%d %b %Y")

    log.info("=" * 70)
    log.info(f"⚔️  APEX SNIPER v1.2 — {date_label}")
    log.info(f"    Bismillah — Unified Halal Swing Intelligence Engine")
    log.info("=" * 70)

    # ── Macro ─────────────────────────────────────────────────────────────
    macro = fetch_macro_regime()

    if macro["macro_state"] == "MASSACRE":
        msg = "💀 MARKET MASSACRE — APEX Sniper halted. No entries today. Stay in cash."
        send_all_telegram([msg])
        log.error("🚨 MASSACRE state — all entries halted")
        return []

    if macro["macro_state"] == "PANIC":
        log.warning("🔴 VIX PANIC — only PROBE-grade entries pass this session")

    # ── Universe ──────────────────────────────────────────────────────────
    data_source = "SHEETS"
    universe    = pd.DataFrame()

    if not FORCE_YFINANCE:
        log.info("Loading BHAVCOPY from Google Sheets...")
        universe = load_bhavcopy_sheets()
        if universe.empty:
            log.warning("Sheets unavailable — falling back to yfinance snapshot")

    if universe.empty and not FORCE_YFINANCE:
        log.info("Building yfinance universe snapshot...")
        universe    = build_universe_yfinance()
        data_source = "YFINANCE"

    if universe.empty and GOOGLE_FINANCE_ENABLED:
        log.info("Building Google Finance universe snapshot...")
        universe    = build_universe_google_finance()
        data_source = "GOOGLE_FINANCE"

    if universe.empty and NSEPYTHON_ENABLED:
        log.info("Building nsepython universe snapshot...")
        universe    = build_universe_nsepython()
        data_source = "NSEPYTHON"

    if universe.empty:
        log.error("❌ No data source available. Abort.")
        return []

    log.info(f"Universe: {len(universe)} rows from {data_source}")

    # Normalise
    for c in ["close", "turnover_lakhs"]:
        if c in universe.columns:
            universe[c] = pd.to_numeric(universe[c], errors="coerce")
    if "turnover_lakhs" not in universe.columns:
        universe["turnover_lakhs"] = 0.0
    universe["symbol"] = universe["symbol"].astype(str).str.strip().str.upper()

    # Pre-filter
    candidates = universe[
        universe["close"].between(MIN_PRICE, MAX_PRICE) &
        (universe["turnover_lakhs"] >= MIN_TURNOVER_LAKHS) &
        universe["symbol"].apply(is_halal)
    ].sort_values("turnover_lakhs", ascending=False).head(200).reset_index(drop=True)

    log.info(f"Candidates after filter: {len(candidates)}")

    # ── FII/DII ───────────────────────────────────────────────────────────
    log.info("Fetching FII/DII data...")
    fii_data = fetch_fii_dii_sheets()
    log.info(f"FII/DII: {fii_data['label']}")

    # ── Main scoring loop ─────────────────────────────────────────────────
    results, screened = [], 0

    for i, (_, row) in enumerate(candidates.iterrows()):
        sym   = row["symbol"]
        close = float(row.get("close", 0))
        tover = float(row.get("turnover_lakhs", 0))

        if i % 20 == 0:
            log.info(f"Progress: {i}/{len(candidates)} | picks so far: {len(results)}")

        try:
            hist = fetch_history(sym, days=300)
            if len(hist) < 30:
                log.debug(f"{sym}: only {len(hist)} bars — skip")
                continue

            screened += 1
            result = score_symbol(sym, hist, close, tover, macro, fii_data)
            if result:
                results.append(result)
                log.info(f"  ✅ {sym} | {result['composite']}/100 | {result['grade']}")

            time.sleep(0.20)

        except Exception as e:
            log.debug(f"{sym}: {e}")

    log.info(f"Screened: {screened} | Picks found: {len(results)}")

    # ── Rank ─────────────────────────────────────────────────────────────
    results.sort(
        key=lambda x: (
            x["composite"] * 1000
            + x["whale_score"] * 10
            + x["vpoc_score"]
        ),
        reverse=True
    )

    # ── Sector cap ────────────────────────────────────────────────────────
    sector_counts: dict = {}
    capped: List[dict]  = []
    for r in results:
        sec = r["sector"]
        if sector_counts.get(sec, 0) < 2:
            capped.append(r)
            sector_counts[sec] = sector_counts.get(sec, 0) + 1

    top_picks = capped[:APEX_TOP_N]

    log.info(f"\n{'=' * 70}")
    log.info(f"⚔️  APEX SNIPER TOP {len(top_picks)} PICKS")
    log.info(f"{'=' * 70}")
    for rank, r in enumerate(top_picks, 1):
        log.info(
            f"#{rank} {r['symbol']:12s} | {r['grade']:15s} | Score {r['composite']}/100 "
            f"| ₹{r['close']} | SL ₹{r['stop_loss']} | R1 ₹{r['r1']} | R2 ₹{r['r2']}"
        )
        log.info(f"     {r['story']}")

    # ── Telegram (CLEAN FORMAT) ─────────────────────────────────────────
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        messages = [format_header_telegram(len(top_picks), date_label, macro, data_source)]
        for rank, r in enumerate(top_picks, 1):
            messages.append(format_pick_telegram_clean(r, rank))
            messages.append("─" * 30)  # Separator between picks
        messages.append(format_footer_telegram(len(top_picks), screened))
        send_all_telegram(messages)
        log.info(f"Telegram sent: {len(messages)} messages")
    else:
        log.info("Telegram not configured — results printed above")

    # ── PAPER MODE ────────────────────────────────────────────────────────
    if PAPER_MODE and top_picks:
        log.info("\n=== PAPER MODE ===")
        for r in top_picks:
            log.info(
                f"{r['symbol']:12s} | Grade {r['grade']} | "
                f"Score {r['composite']}/100 | Entry ₹{r['buy_lo']}-{r['buy_hi']} "
                f"| SL ₹{r['stop_loss']} | R1 ₹{r['r1']} | R2 ₹{r['r2']} | R3 ₹{r['r3']}"
            )

    # ── Persist ───────────────────────────────────────────────────────────
    save_results(top_picks, date_label)

    return top_picks


# ══════════════════════════════════════════════════════════════════════════
# SECTION 17 — FORTRESS INTEGRATION BRIDGE (FIXED)
# ══════════════════════════════════════════════════════════════════════════

# FIX APEX-CRIT-04: MASSACRE/PANIC abort at top
def run_apex_after_fortress(
    fortress_results: List[dict],
    bhavcopy_df: pd.DataFrame,
    fii_data: dict,
) -> List[dict]:
    """Drop-in: call after fortress run_screener_v8() completes."""
    log.info("⚔️  APEX Sniper — Fortress integration mode")
    macro = fetch_macro_regime()

    # FIX: Abort early on MASSACRE/PANIC
    if macro.get("macro_state") in ("MASSACRE", "PANIC"):
        log.warning(f"Macro={macro['macro_state']} — APEX universe scan aborted.")
        return []

    return _run_apex_on_universe(bhavcopy_df, macro, fii_data)


def _run_apex_on_universe(universe: pd.DataFrame, macro: dict, fii_data: dict) -> List[dict]:
    """Internal: score a pre-filtered universe DataFrame."""
    # FIX APEX-CRIT-04: Abort on MASSACRE/PANIC
    if macro.get("macro_state") in ("MASSACRE", "PANIC"):
        log.warning(f"Macro={macro['macro_state']} — APEX universe scan aborted.")
        return []

    for c in ["close", "turnover_lakhs"]:
        if c in universe.columns:
            universe[c] = pd.to_numeric(universe[c], errors="coerce")
    if "turnover_lakhs" not in universe.columns:
        universe["turnover_lakhs"] = 0.0
    universe["symbol"] = universe["symbol"].astype(str).str.strip().str.upper()

    candidates = universe[
        universe["close"].between(MIN_PRICE, MAX_PRICE) &
        (universe["turnover_lakhs"] >= MIN_TURNOVER_LAKHS) &
        universe["symbol"].apply(is_halal)
    ].sort_values("turnover_lakhs", ascending=False).head(200)

    results = []
    for _, row in candidates.iterrows():
        sym   = row["symbol"]
        close = float(row.get("close", 0))
        tover = float(row.get("turnover_lakhs", 0))
        try:
            hist = fetch_history(sym, days=300)
            if len(hist) < 30:
                continue
            r = score_symbol(sym, hist, close, tover, macro, fii_data)
            if r:
                results.append(r)
            time.sleep(0.15)
        except Exception as e:
            log.debug(f"{sym}: {e}")

    results.sort(key=lambda x: x["composite"], reverse=True)
    return results[:APEX_TOP_N]


# ══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    picks = run_apex_sniper()

    print(f"\n{'═' * 70}")
    print(f"⚔️  APEX SNIPER v1.2 — RESULTS")
    print(f"{'═' * 70}")

    if not picks:
        print("No picks today. Either market is in MASSACRE/PANIC, or no setup passed all layers.")
        print("This is the system working correctly — capital preservation is the first rule.")
    else:
        for i, r in enumerate(picks, 1):
            print(f"\n{'─' * 50}")
            print(f"#{i}  {r['symbol']}  {r['grade']}  |  Score {r['composite']}/100")
            print(f"    Sector  : {r['sector']}")
            print(f"    Price   : ₹{r['close']}")
            print(f"    BUY     : ₹{r['buy_lo']} – ₹{r['buy_hi']}")
            print(f"    Stop    : ₹{r['stop_loss']}  (Risk {r['risk_pct']}%)")
            print(f"    R1      : ₹{r['r1']}  (+{r['r1_pct']}%)  → sell {r['sell_r1']}%")
            print(f"    R2      : ₹{r['r2']}  (+{r['r2_pct']}%)  → sell {r['sell_r2']}%")
            print(f"    R3      : ₹{r['r3']}  (+{r['r3_pct']}%)  → sell {r['sell_r3']}%")
            print(f"    Trail   : arms at R2 → ₹{r['trail_stop']}")
            print(f"    Position: {r['pos_label']}")
            print(f"    R1 est  : ~{r['days_to_r1_est']} days  |  Hit prob {r['r1_hit_prob']:.0f}%  |  MC Survival {r['mc_survival']}%")
            print(f"")
            print(f"    Sub-scores:")
            print(f"      VPOC Sniper : {r['vpoc_score']:.0f}/100")
            print(f"      Whale Radar : {r['whale_score']:.0f}/100  {r['whale_signal']}")
            print(f"      Divergence  : {r['div_score']:.0f}/100")
            print(f"      Vol Profile : {r['vp_score']:.0f}/100")
            print(f"      Pattern     : {r['pat_score']:.0f}/100  {r['pat_label']}")
            print(f"      Bayes       : {r['bayes_pct']}%")
            print(f"      MC Survival : {r['mc_survival']}%")
            print(f"")
            print(f"    Why   : {r['story']}")
            print(f"    RSI {r['rsi']} | MFI {r['mfi']} | ADX {r['adx']} | ATR ₹{r['atr14']} | POC ₹{r['poc']}")

    print(f"\n{'═' * 70}")
    print("🤲 Bismillah — trade with discipline, tawakkul, and halal intention")
    print(f"{'═' * 70}")
