"""Weekly review entry point: load → fetch → score → decide → report.

    uv run weekly_review.py
"""
from __future__ import annotations

import os
from datetime import datetime

import yaml

from quant import (
    decision, market, option_flow, options, portfolio, profiles, providers, report, roles,
    scoring, valuation,
)

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG, PORTFOLIO, WATCHLIST, OPTIONS, OUT_DIR = profiles.resolve(ROOT)


def _load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def main() -> None:
    cfg = _load_yaml(CONFIG)
    watch = _load_yaml(WATCHLIST).get("symbols", [])
    cash, holdings = portfolio.load_portfolio(PORTFOLIO)
    strategies = options.load_options(OPTIONS)

    underlyings = {s.underlying for s in strategies}
    symbols = sorted(set(watch) | set(holdings) | underlyings)
    print(f"Fetching data for {len(symbols)} symbols + SPY/QQQ/VIX ...")

    data_cfg = cfg["data"]
    history = providers.fetch_history(
        symbols + ["SPY", "QQQ"], data_cfg["period"], data_cfg["min_rows"]
    )
    vix = providers.fetch_vix(data_cfg["period"])
    sectors = providers.fetch_sectors(symbols)  # for diversification-aware watchlist
    raw_fund = providers.fetch_fundamentals(symbols, cfg)  # report-only valuation hints

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
        # At the cash floor: rotate out a laggard to fund the strongest candidate.
        watchlist_recs = decision.rotation(
            signals, set(holdings), weights, mkt, cfg, total_value, cash_low,
            sectors, history,
        )
    else:
        max_positions = cfg.get("lifecycle", {}).get("max_positions", 8)
        # Count only survivors: names flagged Close this week free their slot now, so the
        # scan and the closes stay consistent within a single run (no false-empty list).
        closing = {r.symbol for r in holding_recs if r.intent == "Close"}
        open_slots = max(0, max_positions - (len(holdings) - len(closing)))
        watchlist_recs = decision.scan_watchlist(
            signals, set(holdings), mkt, cfg, open_slots, total_value, sectors, history
        )
    decision.attach_strategy_hints(holding_recs, cfg["intent_strategy_map"])
    decision.attach_strategy_hints(watchlist_recs, cfg["intent_strategy_map"])

    # Flag held / buy-recommended names with no hand-set target weight (riding the default).
    buy_intents = {"Add Core", "Increase Exposure"}
    configured = cfg.get("target_weights", {})
    default_weight = cfg.get("lifecycle", {}).get("entry_default_weight", 0.05)
    flagged = set(holdings)
    flagged |= {r.symbol for r in holding_recs + watchlist_recs if r.intent in buy_intents}
    unconfigured = sorted(s for s in flagged if s not in configured)
    if unconfigured:
        print(f"⚠️  {len(unconfigured)} symbol(s) using the default {default_weight:.0%} target "
              f"(no target_weights entry): {', '.join(unconfigured)}")
        print("    → add an explicit weight in config.yaml: target_weights to size them intentionally.")

    cash_frac = cash / total_value if total_value else 0.0
    deployable = max(0.0, cash - cfg["cash_band"]["max"] * total_value)
    summary = {
        "cash": cash,
        "total_value": total_value,
        "cash_frac": cash_frac,
        "cash_status": cash_state,
        "deployable": deployable,
        "unconfigured_targets": unconfigured,
        "default_weight": default_weight,
    }

    r = cfg.get("backtest", {}).get("costs", {}).get("cash_apy", 0.04)
    chains: dict[tuple[str, str], dict | None] = {}  # (underlying, expiry) -> IV map, memoized
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
            options.analyze(s, signals[s.underlying].price, datetime.now().date(), ivs, r)
        )

    # Option-chain positioning (report-only) for the actionable set: held + watchlist names.
    positioning = {}
    if cfg.get("option_positioning", {}).get("enabled", False):
        actionable = {r.symbol for r in holding_recs} | {r.symbol for r in watchlist_recs}
        for sym in sorted(actionable):
            if sym not in signals or sym not in history:
                continue
            p = option_flow.analyze(sym, signals[sym].price, history[sym], cfg)
            if p is not None:
                positioning[sym] = p
        print(f"  option positioning: {len(positioning)}/{len(actionable)} chains analysed")

    # Horizon roles (report-only) for the actionable set: core / swing / momentum + TP/SL.
    roleviews = {}
    if cfg.get("role_rules"):
        for sym in {r.symbol for r in holding_recs} | {r.symbol for r in watchlist_recs}:
            if sym in signals:
                roleviews[sym] = roles.build(sym, signals[sym], fundamentals.get(sym), cfg)

    os.makedirs(OUT_DIR, exist_ok=True)
    now = datetime.now()
    generated_at = now.strftime("%Y-%m-%d %H:%M:%S")  # in-file header + JSON field
    stamp = now.strftime("%Y-%m-%d_%H%M%S")           # filename suffix (sortable, no colons)
    md_path = os.path.join(OUT_DIR, f"weekly_report_{stamp}.md")
    json_path = os.path.join(OUT_DIR, f"weekly_report_{stamp}.json")
    report.generate(
        md_path,
        json_path,
        generated_at,
        mkt,
        holding_recs,
        watchlist_recs,
        option_analyses,
        summary,
        fundamentals,
        positioning,
        roleviews,
    )
    print(f"Report written to {md_path}")


if __name__ == "__main__":
    main()
