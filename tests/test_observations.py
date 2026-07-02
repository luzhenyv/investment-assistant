from datetime import date, timedelta

import polars as pl

from quant import observations
from quant.models import MacroState, MarketState, Signal
from quant.pipeline import AnalysisContext


def _close_from_returns(returns):
    close = [100.0]
    for r in returns:
        close.append(close[-1] * (1.0 + r))
    return close


def _history(closes):
    n = len(closes)
    return pl.DataFrame({
        "date": [date(2026, 1, 1) + timedelta(days=i) for i in range(n)],
        "Close": closes,
    })


def _signal(symbol, price):
    return Signal(
        symbol=symbol, price=price, ma20=price, ma50=price, ma200=price,
        rsi=50.0, atr=2.0, high_52w=price, low_52w=price,
        trend_score=50.0, momentum_score=40.0, pullback=False, breakout=False,
        state="Range",
    )


def test_build_rows_flags_statistical_price_move():
    closes = _close_from_returns([-0.01, 0.0, 0.01, 0.02, 0.03, 0.04])
    sym = "MOVE"
    sig = _signal(sym, closes[-1])
    ctx_kwargs = {
        "cfg": {
            "drift_band": 0.20,
            "scoring": {"rsi_overbought": 70, "rsi_oversold": 40},
            "daily_review": {"price_move": {"lookback": 5, "abnormal_z": 1.5}},
        },
        "watch": [], "cash": 0.0, "holdings": {}, "strategies": {},
        "history": {sym: _history(closes)}, "vix": 15.0, "sectors": {},
        "signals": {sym: sig}, "spy": sig, "qqq": sig, "mkt": MarketState("Neutral", 50.0),
        "macro_state": MacroState({}, "neutral", "flat", "normal", "neutral", "neutral", "neutral"),
        "fundamentals": {}, "prices": {sym: closes[-1]}, "total_value": 10000.0,
        "weights": {}, "cash_state": "ok", "cash_low": False, "cash_frac": 0.0,
        "deployable": 0.0, "holding_recs": [], "watchlist_recs": [], "option_analyses": [],
        "positioning": {}, "roleviews": {}, "summary": {},
    }
    if "sector_state" in AnalysisContext.__dataclass_fields__:
        ctx_kwargs["sector_state"] = None
    ctx = AnalysisContext(**ctx_kwargs)

    _, outliers = observations.build_rows(
        ctx, cadence="daily", prior_states={}, git_sha=None, config_hash="test",
        generated_at="2026-01-07 00:00:00 UTC",
        ohlcv={sym: {"bar_date": "2026-01-06", "open": 0, "high": 0, "low": 0}},
    )

    assert outliers[0]["symbol"] == sym
    assert outliers[0]["flags"] == ["Abnormal price move (+1.9σ)"]
