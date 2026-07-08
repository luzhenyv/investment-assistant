from datetime import date, timedelta

import polars as pl

from quant import observations
from quant.models import MacroState, MarketState, Signal, Zone
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


def _signal(symbol, price, atr=2.0):
    return Signal(
        symbol=symbol, price=price, ma20=price, ma50=price, ma200=price,
        rsi=50.0, atr=atr, high_52w=price, low_52w=price,
        trend_score=50.0, momentum_score=40.0, pullback=False, breakout=False,
        state="Range",
    )


def _ctx(sym, closes, sig, daily_review, levels=None):
    ctx_kwargs = {
        "cfg": {
            "drift_band": 0.20,
            "scoring": {"rsi_overbought": 70, "rsi_oversold": 40},
            "daily_review": daily_review,
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
    if "levels" in AnalysisContext.__dataclass_fields__:
        ctx_kwargs["levels"] = levels or {}
    if "levels_source" in AnalysisContext.__dataclass_fields__:
        ctx_kwargs["levels_source"] = {s: "manual" for s in (levels or {})}
    return AnalysisContext(**ctx_kwargs)


def test_build_rows_flags_statistical_price_move():
    closes = _close_from_returns([-0.01, 0.0, 0.01, 0.02, 0.03, 0.04])
    sym = "MOVE"
    ctx = _ctx(
        sym, closes, _signal(sym, closes[-1]),
        {"price_move": {"lookback": 5, "abnormal_z": 1.5}, "atr_move": {"abnormal_mult": 10.0}},
    )

    _, outliers = observations.build_rows(
        ctx, cadence="daily", prior_states={}, git_sha=None, config_hash="test",
        generated_at="2026-01-07 00:00:00 UTC",
        ohlcv={sym: {"bar_date": "2026-01-06", "open": 0, "high": 0, "low": 0}},
    )

    assert outliers[0]["symbol"] == sym
    assert outliers[0]["flags"] == ["Abnormal price move (+1.9σ)"]


def test_build_rows_flags_atr_move():
    closes = _close_from_returns([0.01, -0.01, 0.01, -0.01, 0.01, 0.04])
    sym = "ATR"
    ctx = _ctx(
        sym, closes, _signal(sym, closes[-1], atr=2.0),
        {
            "price_move": {"lookback": 5, "abnormal_z": 10.0},
            "atr_move": {"abnormal_mult": 1.5},
        },
    )

    _, outliers = observations.build_rows(
        ctx, cadence="daily", prior_states={}, git_sha=None, config_hash="test",
        generated_at="2026-01-07 00:00:00 UTC",
        ohlcv={sym: {"bar_date": "2026-01-06", "open": 0, "high": 0, "low": 0}},
    )

    assert outliers[0]["symbol"] == sym
    assert outliers[0]["flags"] == ["Abnormal ATR move (+2.0x ATR)"]


_SR_COLS = ["nearest_support", "nearest_resistance", "sr_support_label", "sr_support_methods",
            "sr_resistance_label", "sr_resistance_methods", "sr_dist_support_pct",
            "sr_dist_resistance_pct"]


def test_build_rows_sr_columns_null_when_levels_absent():
    closes = _close_from_returns([0.0, 0.01, 0.0, 0.01, 0.0, 0.01])
    sym = "NOSR"
    ctx = _ctx(sym, closes, _signal(sym, closes[-1]),
               {"price_move": {"lookback": 5}, "atr_move": {}})  # levels default {} → nulls
    rows, _ = observations.build_rows(
        ctx, cadence="daily", prior_states={}, git_sha=None, config_hash="test",
        generated_at="2026-01-07 00:00:00 UTC",
        ohlcv={sym: {"bar_date": "2026-01-06", "open": 0, "high": 0, "low": 0}},
    )
    for col in _SR_COLS + ["sr_source"]:
        assert col in observations.SCHEMA
        assert rows[0][col] is None


def test_build_rows_sr_columns_populated_from_levels():
    closes = _close_from_returns([0.0, 0.01, 0.0, 0.01, 0.0, 0.01])
    sym = "HASSR"
    price = closes[-1]
    zones = [
        Zone(low=price * 0.9, high=price * 0.92, score=1.0, label="strong",
             kind="support", touches=1, methods=["fib", "swing", "volume"]),
        Zone(low=price * 1.08, high=price * 1.10, score=1.0, label="medium",
             kind="resistance", touches=1, methods=["fib", "round"]),
    ]
    ctx = _ctx(sym, closes, _signal(sym, price),
               {"price_move": {"lookback": 5}, "atr_move": {}}, levels={sym: zones})
    rows, _ = observations.build_rows(
        ctx, cadence="daily", prior_states={}, git_sha=None, config_hash="test",
        generated_at="2026-01-07 00:00:00 UTC",
        ohlcv={sym: {"bar_date": "2026-01-06", "open": 0, "high": 0, "low": 0}},
    )
    row = rows[0]
    assert row["sr_support_label"] == "strong" and row["sr_support_methods"] == 3
    assert row["sr_resistance_label"] == "medium" and row["sr_resistance_methods"] == 2
    assert row["nearest_support"] < price < row["nearest_resistance"]
    assert row["sr_dist_support_pct"] < 0 < row["sr_dist_resistance_pct"]
    assert row["sr_source"] == "manual"   # fixture tags curated symbols manual
