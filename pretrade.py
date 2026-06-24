"""Pre-trade ('Monday pre-flight') brief for the names you're about to act on.

The weekly engine runs on daily *cached* bars, so its report is a session behind by the time you
trade. This refreshes one or more symbols against LIVE data — intraday quote, next-earnings date,
and option-positioning levels re-anchored to the live price — so you can time the entry/exit the
weekly report only hinted at. Catalyst/news judgment is the `pretrade-check` skill's job.

    uv run pretrade.py MU [NVDA ...]
"""
from __future__ import annotations

import os
import sys

import yaml

from quant import (
    clock, decision, option_flow, portfolio, pretrade, pretrade_report, profiles, providers, roles,
    scoring, valuation,
)

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG, PORTFOLIO, _WATCHLIST, _OPTIONS, OUT_DIR = profiles.resolve(ROOT)


def _load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def main() -> None:
    tickers = [t.upper() for t in sys.argv[1:]]
    if not tickers:
        raise SystemExit("usage: uv run pretrade.py SYM [SYM ...]")

    cfg = _load_yaml(CONFIG)
    data_cfg = cfg["data"]
    cash, holdings = portfolio.load_portfolio(PORTFOLIO)
    print(f"Pre-trade brief for {', '.join(tickers)} (+ book/SPY/QQQ context) ...")

    # Price the whole book (held names too) so total value / deployable / current weights are real.
    fetch_syms = sorted(set(tickers) | set(holdings) | {"SPY", "QQQ"})
    history = providers.fetch_history(fetch_syms, data_cfg["period"], data_cfg["min_rows"])
    raw_fund = providers.fetch_fundamentals(tickers, cfg)
    vix = providers.fetch_vix(data_cfg["period"])

    prices = {
        sym: float(df["Close"].tail(1).item())
        for sym, df in history.items() if sym not in ("SPY", "QQQ")
    }
    missing = [s for s in holdings if s not in prices]
    if missing:
        print(f"  ! no price for held {', '.join(missing)} — counted as $0 in total value")
    total_value = portfolio.portfolio_value(cash, holdings, prices)
    weights = portfolio.current_weights(holdings, prices, total_value)
    cash_state = portfolio.cash_status(cash, total_value, cfg["cash_band"])
    cash_frac = cash / total_value if total_value else 0.0
    deployable = max(0.0, cash - cfg["cash_band"]["max"] * total_value)
    portfolio_ctx = {
        "cash": cash, "total_value": total_value, "cash_frac": cash_frac,
        "cash_status": cash_state, "deployable": deployable,
    }
    max_steps = cfg.get("lifecycle", {}).get("max_steps", 3)

    spy_q, qqq_q = providers.fetch_quote("SPY"), providers.fetch_quote("QQQ")
    market_ctx = {
        "spy_change_pct": spy_q["change_pct"] if spy_q else None,
        "qqq_change_pct": qqq_q["change_pct"] if qqq_q else None,
        "vix": vix,
    }

    now = clock.now()
    generated_at = clock.timestamp(now)
    briefs = []
    for sym in tickers:
        if sym not in history:
            print(f"  ! skipping {sym}: no usable history")
            continue
        sig = scoring.build_signal(sym, history[sym], cfg)
        raw = raw_fund.get(sym)
        fund = valuation.build(sym, raw, sig.price, cfg, stale=raw.get("_stale", False)) if raw else None
        positioning = (option_flow.analyze(sym, sig.price, history[sym], cfg)
                       if cfg.get("option_positioning", {}).get("enabled", False) else None)
        roleview = roles.build(sym, sig, fund, cfg) if cfg.get("role_rules") else None
        live = providers.fetch_quote(sym)
        if live is None:
            print(f"  ! {sym}: live quote unavailable — falling back to last daily close")
        earnings = providers.fetch_earnings_date(sym)

        h = holdings.get(sym)
        target = decision.effective_target(sym, cfg)
        cur_w = weights.get(sym, 0.0)
        position = {
            "held": h is not None,
            "shares": h.shares if h else 0.0,
            "core": h.core if h else 0.0,
            "trading": h.trading if h else 0.0,
            "avg_cost": h.avg_cost if h else None,
            "current_weight": cur_w,
            "target_weight": target,
            "gap_to_target": max(0.0, (target - cur_w)) * total_value,
            "step_size": (target / max_steps) * total_value if max_steps else None,
        }
        briefs.append(pretrade.build(
            sym, cfg, sig, live, positioning, roleview, fund, earnings, market_ctx,
            portfolio_ctx, position, as_of=generated_at,
        ))

    if not briefs:
        raise SystemExit("No briefs produced — check the tickers.")

    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = clock.file_stamp(now)
    md_path = os.path.join(OUT_DIR, f"pretrade_{stamp}.md")
    json_path = os.path.join(OUT_DIR, f"pretrade_{stamp}.json")
    pretrade_report.generate(md_path, json_path, generated_at, briefs)
    print(f"Pre-trade brief written to {md_path}")


if __name__ == "__main__":
    main()
