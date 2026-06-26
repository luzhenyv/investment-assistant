"""Daily review entry point: run AFTER the close to capture the day and accumulate a database.

Same engine as weekly_review.py (load → fetch → score → decide → report) but on a daily cadence,
with two additions: (1) an abnormal-volume overlay (RVOL + z-score) and an outliers section the
`daily-review` skill explains; (2) it APPENDS one row per symbol to a growing parquet store at
data/daily_observations/<profile>/<YYYY-MM-DD>.parquet — so the day's indicators, scores, and the
engine's per-symbol judgment (state + next-day intent) accumulate as a labelled time series to mine
and grade later. The judgment is a label; the store is the database.

    uv run daily_review.py
"""
from __future__ import annotations

import glob
import os
import subprocess

import polars as pl
import yaml

from quant import (
    clock, daily_report, decision, market, observations, option_flow, options, portfolio, profiles,
    providers, roles, scoring, valuation,
)

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG, PORTFOLIO, WATCHLIST, OPTIONS, OUT_DIR = profiles.resolve(ROOT)
PROFILE = os.environ.get("PROFILE", "demo")
STORE = os.path.join(ROOT, "data", "daily_observations", PROFILE)


def _load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _git_sha(root: str) -> str | None:
    """Short HEAD SHA for run provenance; None if not a git checkout / git unavailable."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=root, text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:  # noqa: BLE001
        return None


def _day_change(df: pl.DataFrame) -> float | None:
    """Latest close vs the prior close, as a fraction (None if <2 bars)."""
    close = df["Close"]
    if close.len() < 2:
        return None
    prev = float(close.tail(2).head(1).item())
    return float(close.tail(1).item()) / prev - 1.0 if prev else None


def _last_bar(df: pl.DataFrame) -> dict:
    """The latest daily bar (date + OHLCV) for human verification of the record."""
    last = df.tail(1)
    return {
        "bar_date": str(last["date"].item()),
        "open": round(float(last["Open"].item()), 2),
        "high": round(float(last["High"].item()), 2),
        "low": round(float(last["Low"].item()), 2),
        "close": round(float(last["Close"].item()), 2),
        "volume": round(float(last["Volume"].item())),
    }


def _prior_states(as_of_bar: str) -> dict[str, str]:
    """Load the most recent prior daily parquet (before this session) → {symbol: state}, for
    detecting state flips. Empty dict on the first run / no prior file."""
    files = sorted(glob.glob(os.path.join(STORE, "*.parquet")))
    current = f"{as_of_bar}.parquet"
    prior = [f for f in files if os.path.basename(f) < current]
    if not prior:
        return {}
    df = pl.read_parquet(prior[-1])
    return dict(zip(df["symbol"].to_list(), df["state"].to_list()))


def main() -> None:
    cfg = _load_yaml(CONFIG)
    watch = _load_yaml(WATCHLIST).get("symbols", [])
    cash, holdings = portfolio.load_portfolio(PORTFOLIO)
    strategies = options.load_options(OPTIONS)

    underlyings = {s.underlying for s in strategies}
    symbols = sorted(set(watch) | set(holdings) | underlyings)
    print(f"Fetching data for {len(symbols)} symbols + SPY/QQQ/VIX ...")

    data_cfg = cfg["data"]
    # Force a fresh fetch: the daily review runs after the close and must capture TODAY's bar even if
    # an earlier same-day run cached a file holding only the prior session (see cache.load_or_fetch).
    history = providers.fetch_history(
        symbols + ["SPY", "QQQ"], data_cfg["period"], data_cfg["min_rows"], force_refresh=True
    )
    vix = providers.fetch_vix(data_cfg["period"])
    sectors = providers.fetch_sectors(symbols)
    raw_fund = providers.fetch_fundamentals(symbols, cfg)

    signals = {
        sym: scoring.build_signal(sym, df, cfg)
        for sym, df in history.items()
        if sym not in ("SPY", "QQQ")
    }
    if "SPY" not in history or "QQQ" not in history:
        raise SystemExit("Could not fetch SPY/QQQ — cannot determine market regime.")
    spy = scoring.build_signal("SPY", history["SPY"], cfg)
    qqq = scoring.build_signal("QQQ", history["QQQ"], cfg)
    mkt = market.detect_market(spy, qqq, vix)

    fundamentals = {
        sym: valuation.build(sym, raw, signals[sym].price, cfg, stale=raw.get("_stale", False))
        for sym, raw in raw_fund.items()
        if raw and sym in signals
    }

    prices = {sym: s.price for sym, s in signals.items()}
    total_value = portfolio.portfolio_value(cash, holdings, prices)
    weights = portfolio.current_weights(holdings, prices, total_value)
    cash_state = portfolio.cash_status(cash, total_value, cfg["cash_band"])
    cash_low = cash_state == "low"

    holding_recs = []
    for sym, h in sorted(holdings.items()):
        if sym not in signals:
            continue
        holding_recs.append(
            decision.decide_holding(
                sig=signals[sym],
                holding=h,
                market=mkt,
                current_weight=weights.get(sym, 0.0),
                target_weight=decision.effective_target(sym, cfg),
                total_value=total_value,
                cfg=cfg,
                cash_low=cash_low,
            )
        )

    if cash_low:
        watchlist_recs = decision.rotation(
            signals, set(holdings), weights, mkt, cfg, total_value, cash_low,
            sectors, history,
        )
    else:
        max_positions = cfg.get("lifecycle", {}).get("max_positions", 8)
        closing = {r.symbol for r in holding_recs if r.intent == "Close"}
        open_slots = max(0, max_positions - (len(holdings) - len(closing)))
        watchlist_recs = decision.scan_watchlist(
            signals, set(holdings), mkt, cfg, open_slots, total_value, sectors, history
        )
    decision.attach_strategy_hints(holding_recs, cfg["intent_strategy_map"])
    decision.attach_strategy_hints(watchlist_recs, cfg["intent_strategy_map"])

    cash_frac = cash / total_value if total_value else 0.0
    deployable = max(0.0, cash - cfg["cash_band"]["max"] * total_value)
    summary = {
        "cash": cash,
        "total_value": total_value,
        "cash_frac": cash_frac,
        "cash_status": cash_state,
        "deployable": deployable,
    }

    r = cfg.get("backtest", {}).get("costs", {}).get("cash_apy", 0.04)
    chains: dict[tuple[str, str], dict | None] = {}
    option_analyses = []
    for s in strategies:
        if s.underlying not in signals:
            print(f"  ! skipping option {s.id}: no price for {s.underlying}")
            continue
        ivs: dict[tuple[str, float, str], float] = {}
        for leg in s.legs:
            if leg.expiry is None:
                continue
            expiry = leg.expiry.isoformat()
            key = (s.underlying, expiry)
            if key not in chains:
                chains[key] = providers.fetch_option_chain(s.underlying, expiry)
                if chains[key] is None:
                    print(f"  ! no option chain for {s.underlying} {expiry} — Greeks unavailable")
            chain = chains[key]
            if chain and (leg.right, float(leg.strike)) in chain:
                ivs[(leg.right, float(leg.strike), expiry)] = chain[(leg.right, float(leg.strike))]
        option_analyses.append(
            options.analyze(s, signals[s.underlying].price, clock.today(), ivs, r)
        )

    actionable = {r.symbol for r in holding_recs} | {r.symbol for r in watchlist_recs}

    # Positioning for the FULL universe (not just actionable) so the DB has walls/max-pain/IV for
    # every portfolio + watchlist name. One option-chain fetch per symbol — fine for an EOD batch;
    # analyze() returns None for thin / non-optionable chains.
    positioning = {}
    if cfg.get("option_positioning", {}).get("enabled", False):
        for sym in sorted(signals):
            if sym not in history:
                continue
            p = option_flow.analyze(sym, signals[sym].price, history[sym], cfg)
            if p is not None:
                positioning[sym] = p
        print(f"  option positioning: {len(positioning)}/{len(signals)} chains analysed")

    # Roles for the FULL universe (cheap, no I/O).
    roleviews = {}
    if cfg.get("role_rules"):
        for sym in signals:
            roleviews[sym] = roles.build(sym, signals[sym], fundamentals.get(sym), cfg)

    # --- Daily additions: comprehensive observation rows (the database) + outliers (skill entry) ---
    rec_by_sym = {r.symbol: r for r in holding_recs + watchlist_recs}
    watch_set = set(watch)
    overbought = cfg["scoring"]["rsi_overbought"]
    oversold = cfg["scoring"]["rsi_oversold"]
    now = clock.now()
    as_of_date = clock.datestamp(now)
    generated_at = clock.timestamp(now)

    # Raw daily bar per symbol (date + OHLCV) for verification, and a freshness check: the close is
    # only "today's" if the latest bar IS today. Warn loudly otherwise (market still open / weekend /
    # holiday / vendor lag) so a stale prior-session close isn't mistaken for the session just closed.
    # as_of_bar (the session) keys the file/sidecar below, so it must be resolved before they are written.
    ohlcv = {sym: _last_bar(history[sym]) for sym in signals}
    as_of_bar = max((b["bar_date"] for b in ohlcv.values()), default=as_of_date)
    stale = as_of_bar < as_of_date
    if stale:
        print(f"  ⚠ latest daily bar is {as_of_bar}, not today {as_of_date} — close is the PRIOR "
              f"session (market still open, weekend/holiday, or vendor lag). Run after the close.")

    prior_states = _prior_states(as_of_bar)

    # Provenance: stamp every row with the code + hyperparameter set that produced it, and snapshot
    # the resolved config to a sidecar so a historical decision can be replayed / re-optimized later.
    git_sha = _git_sha(ROOT)
    config_hash = observations.record_run_meta(STORE, as_of_bar, cfg, git_sha, generated_at)
    holdings_count = len(holdings)

    rows, outliers = [], []
    for sym in sorted(signals):
        s = signals[sym]
        f = fundamentals.get(sym)
        p = positioning.get(sym)
        rv = roleviews.get(sym)
        rec = rec_by_sym.get(sym)
        h = holdings.get(sym)
        intent = rec.intent if rec else ""
        membership = "holding" if sym in holdings else "watchlist" if sym in watch_set else "underlying"
        target_weight = decision.effective_target(sym, cfg)
        rows.append({
            "create_time": generated_at, "symbol": sym, "membership": membership,
            "regime": mkt.regime, "bull_score": round(mkt.bull_score, 1), "vix": round(vix, 1),
            "price": round(s.price, 2), "day_change_pct": _day_change(history[sym]),
            "volume": round(s.volume), "rvol": round(s.rvol, 2), "vol_z": round(s.vol_z, 2),
            "vol_state": s.vol_state,
            "ma20": round(s.ma20, 2), "ma50": round(s.ma50, 2), "ma200": round(s.ma200, 2),
            "rsi": round(s.rsi, 1), "atr": round(s.atr, 2),
            "high_52w": round(s.high_52w, 2), "low_52w": round(s.low_52w, 2),
            "trend_score": s.trend_score, "momentum_score": s.momentum_score, "rs": round(s.rs, 4),
            "state": s.state,
            "sector": f.sector if f else None, "pe": f.pe if f else None,
            "forward_pe": f.forward_pe if f else None, "peg": f.peg if f else None,
            "pb": f.pb if f else None, "ev_ebitda": f.ev_ebitda if f else None,
            "analyst_target": f.analyst_target if f else None,
            "upside_to_target": f.upside_to_target if f else None,
            "valuation_label": f.valuation_label if f else None, "beta": f.beta if f else None,
            "put_wall": p.put_wall if p else None, "call_wall": p.call_wall if p else None,
            "max_pain": p.max_pain if p else None, "em": p.em if p else None,
            "em_pct": p.em_pct if p else None, "pc_oi": p.pc_oi if p else None,
            "pc_vol": p.pc_vol if p else None, "atm_iv": p.atm_iv if p else None,
            "iv_skew": p.iv_skew if p else None, "reward": p.reward if p else None,
            "risk": p.risk if p else None, "rr_ratio": p.rr_ratio if p else None,
            "role": rv.role if rv else None, "suggested_role": rv.suggested_role if rv else None,
            "horizon": rv.horizon if rv else None, "tp_price": rv.tp_price if rv else None,
            "sl_price": rv.sl_price if rv else None,
            "intent": intent, "reason": rec.reason if rec else "",
            "dollar_gap": rec.dollar_gap if rec else None,
            "strategy_hint": "; ".join(rec.strategy_hint) if rec and rec.strategy_hint else "",
            # decision-context factors that gate the intent
            "current_weight": round(weights.get(sym, 0.0), 4), "target_weight": round(target_weight, 4),
            "ceiling": round(decision.effective_ceiling(s.state, target_weight, cfg), 4),
            "pullback": s.pullback, "breakout": s.breakout,
            # position composition (null when not held)
            "shares": h.shares if h else None, "core": h.core if h else None,
            "trading": h.trading if h else None, "avg_cost": h.avg_cost if h else None,
            # book / market context (constant across the day's rows)
            "cash": round(cash), "total_value": round(total_value), "cash_frac": round(cash_frac, 4),
            "cash_status": cash_state, "cash_low": cash_low, "holdings_count": holdings_count,
            "spy_trend": spy.trend_score, "qqq_trend": qqq.trend_score,
            # fundamentals fill-out
            "profit_margin": f.profit_margin if f else None,
            "rev_growth": f.rev_growth if f else None, "eps_growth": f.eps_growth if f else None,
            # reproducibility
            "git_sha": git_sha, "config_hash": config_hash,
            # raw daily bar for verification (close == price, volume == volume above)
            "bar_date": ohlcv[sym]["bar_date"], "open": ohlcv[sym]["open"],
            "high": ohlcv[sym]["high"], "low": ohlcv[sym]["low"],
        })

        prev = prior_states.get(sym)
        flags = []
        if s.vol_state != "Normal":
            flags.append(f"{s.vol_state} volume")
        if prev and prev != s.state:
            flags.append("state change")
        if s.rsi >= overbought:
            flags.append("RSI overbought")
        elif s.rsi <= oversold:
            flags.append("RSI oversold")
        if flags:
            outliers.append({
                "symbol": sym, "flags": flags, "day_change_pct": _day_change(history[sym]),
                "rvol": round(s.rvol, 2), "vol_z": round(s.vol_z, 2), "vol_state": s.vol_state,
                "state": s.state, "prev_state": prev, "rsi": round(s.rsi, 1), "intent": intent,
            })

    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = clock.file_stamp(now)
    md_path = os.path.join(OUT_DIR, f"daily_review_{stamp}.md")
    json_path = os.path.join(OUT_DIR, f"daily_review_{stamp}.json")
    # Report shows positioning for the actionable set only (keeps the .md focused); the full
    # universe positioning still lands in the observation store above.
    report_positioning = {k: v for k, v in positioning.items() if k in actionable}
    daily_report.generate(
        md_path, json_path, generated_at, mkt, holding_recs, watchlist_recs, option_analyses,
        summary, fundamentals, report_positioning, roleviews, outliers,
        ohlcv=ohlcv, as_of_bar=as_of_bar, stale=stale,
    )
    print(f"Report written to {md_path}")
    print(f"  {len(outliers)} outlier(s) flagged")
    print("  " + observations.record(STORE, as_of_bar, rows))


if __name__ == "__main__":
    main()
