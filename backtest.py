"""Backtest entry point: load config → fetch (cached) history → replay the weekly
strategy → print + write a summary.

    uv run backtest.py
"""
from __future__ import annotations

import json
import os

import yaml

from quant import backtest, portfolio, providers

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
    _, holdings = portfolio.load_portfolio(PORTFOLIO)

    symbols = sorted(set(watch) | set(holdings) | {"SPY", "QQQ"})
    data_cfg = cfg["data"]
    print(f"Fetching history for {len(symbols)} symbols + VIX ...")
    history = providers.fetch_history(symbols, data_cfg["period"], data_cfg["min_rows"])
    vix_hist = providers.fetch_vix_history(data_cfg["period"])

    result = backtest.run(history, vix_hist, cfg)

    print("\nBacktest — weekly strategy replay")
    print(f"  Period:        {result.dates[0]} → {result.dates[-1]} ({len(result.dates)} weeks)")
    print(f"  Initial:       ${result.initial_value:,.0f}")
    print(f"  Final:         ${result.final_value:,.0f}")
    print(f"  Total return:  {result.total_return:+.1%}   (SPY buy-hold {result.spy_return:+.1%})")
    print(f"  CAGR:          {result.cagr:+.1%}")
    print(f"  Max drawdown:  {result.max_drawdown:.1%}")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "backtest_report.json")
    with open(out, "w") as f:
        json.dump(
            {
                "summary": {
                    "initial_value": result.initial_value,
                    "final_value": result.final_value,
                    "total_return": result.total_return,
                    "cagr": result.cagr,
                    "max_drawdown": result.max_drawdown,
                    "spy_return": result.spy_return,
                },
                "equity_curve": [
                    {"date": d, "equity": e} for d, e in zip(result.dates, result.equity)
                ],
            },
            f,
            indent=2,
        )
    print(f"\nEquity curve written to {out}")


if __name__ == "__main__":
    main()
