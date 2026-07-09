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

from quant import (
    clock, decision, news, observations, option_flow, pipeline, pretrade, pretrade_report, profiles,
    providers, roles, scoring, sentiment, valuation,
)

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG, PORTFOLIO, _WATCHLIST, _OPTIONS, OUT_DIR = profiles.resolve(ROOT)
PROFILE = os.environ.get("PROFILE", "demo")
STORE = os.path.join(ROOT, "data", "daily_observations", PROFILE)


def main() -> None:
    tickers = [t.upper() for t in sys.argv[1:]]
    if not tickers:
        raise SystemExit("usage: uv run pretrade.py SYM [SYM ...]")

    cfg, _watch, cash, holdings, _strategies = pipeline.load_inputs(
        CONFIG, PORTFOLIO, _WATCHLIST, _OPTIONS
    )
    data_cfg = cfg["data"]
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
    total_value, weights, cash_state, cash_frac, deployable = pipeline.book_math(
        cash, holdings, prices, cfg
    )
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

    opt_enabled = cfg.get("option_positioning", {}).get("enabled", False)
    iv_hist = observations.atm_iv_history(STORE) if opt_enabled else {}
    sent_enabled = cfg.get("sentiment", {}).get("enabled", False)
    sent_vol_hist = observations.sentiment_volume_history(STORE) if sent_enabled else {}
    news_enabled = cfg.get("news", {}).get("enabled", False)
    news_vol_hist = observations.news_volume_history(STORE) if news_enabled else {}

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
        positioning = (option_flow.analyze(sym, sig.price, history[sym], cfg, iv_hist=iv_hist.get(sym))
                       if opt_enabled else None)
        roleview = roles.build(sym, sig, fund, cfg) if cfg.get("role_rules") else None
        sentiment_view = (sentiment.analyze(sym, providers.fetch_sentiment_raw(sym, cfg), cfg,
                                            vol_hist=sent_vol_hist.get(sym)) if sent_enabled else None)
        news_view = (news.analyze(sym, providers.fetch_news_raw(sym, cfg), cfg,
                                  vol_hist=news_vol_hist.get(sym)) if news_enabled else None)
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
            portfolio_ctx, position, as_of=generated_at, sentiment_view=sentiment_view,
            news_view=news_view,
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
