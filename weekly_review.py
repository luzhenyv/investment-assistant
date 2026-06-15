"""Weekly review entry point: load → fetch → score → decide → report.

    uv run weekly_review.py
"""
from __future__ import annotations

import os
from datetime import date

import yaml

from quant import decision, market, portfolio, providers, report, scoring

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(ROOT, "config", "config.yaml")
PORTFOLIO = os.path.join(ROOT, "data", "portfolio.yaml")
WATCHLIST = os.path.join(ROOT, "data", "watchlist.yaml")
OUT_DIR = os.path.join(ROOT, "output")


def _load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def main() -> None:
    cfg = _load_yaml(CONFIG)
    watch = _load_yaml(WATCHLIST).get("symbols", [])
    cash, holdings = portfolio.load_portfolio(PORTFOLIO)

    symbols = sorted(set(watch) | set(holdings))
    print(f"Fetching data for {len(symbols)} symbols + SPY/QQQ/VIX ...")

    history = providers.fetch_history(symbols + ["SPY", "QQQ"])
    vix = providers.fetch_vix()

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

    prices = {sym: s.price for sym, s in signals.items()}
    total_value = portfolio.portfolio_value(cash, holdings, prices)
    weights = portfolio.current_weights(holdings, prices, total_value)
    cash_state = portfolio.cash_status(cash, total_value, cfg["cash_band"])
    cash_low = cash_state == "low"
    targets = cfg.get("target_weights", {})

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
                target_weight=targets.get(sym, 0.0),
                total_value=total_value,
                cfg=cfg,
                cash_low=cash_low,
            )
        )

    watchlist_recs = decision.scan_watchlist(signals, set(holdings), mkt)
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

    os.makedirs(OUT_DIR, exist_ok=True)
    generated_at = date.today().isoformat()
    report.generate(
        os.path.join(OUT_DIR, "weekly_report.md"),
        os.path.join(OUT_DIR, "weekly_report.json"),
        generated_at,
        mkt,
        holding_recs,
        watchlist_recs,
        summary,
    )
    print(f"Report written to {OUT_DIR}/weekly_report.md")


if __name__ == "__main__":
    main()
