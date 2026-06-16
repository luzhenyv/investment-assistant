import datetime as dt

import polars as pl

from quant import backtest
from quant.models import Recommendation

CFG = {
    "drift_band": 0.20,
    "cash_band": {"min": 0.10, "max": 0.25},
    "scoring": {"rsi_overbought": 70, "rsi_oversold": 40, "pullback_atr_mult": 0.5},
    "target_weights": {"MSFT": 0.50},
}


def _rising_frame(n=260, base=100.0):
    start = dt.date(2023, 1, 2)
    dates = pl.date_range(start, start + dt.timedelta(days=n - 1), "1d", eager=True)
    close = [base + i for i in range(n)]
    # High == Close so each new closing high registers as a 52w breakout, which
    # is what makes scan_watchlist surface (and the sim buy) the name in a bull run.
    return pl.DataFrame(
        {
            "date": dates,
            "Open": close,
            "High": close,
            "Low": [c - 1 for c in close],
            "Close": close,
        }
    )


def test_run_produces_equity_curve_and_buys_in_bull():
    history = {"SPY": _rising_frame(), "QQQ": _rising_frame(), "MSFT": _rising_frame()}
    result = backtest.run(history, vix_hist=None, cfg=CFG, initial_cash=100_000.0)

    assert len(result.dates) == len(result.equity) > 0
    assert result.final_value > 0
    # Rising market -> SPY buy-hold is positive and capital gets deployed.
    assert result.spy_return > 0
    assert result.final_value > result.initial_value


def test_close_sells_to_zero():
    shares = {"MSFT": 100.0}
    prices = {"MSFT": 50.0}
    recs = [Recommendation(symbol="MSFT", intent="Close", reason="")]
    cash = backtest._execute(
        recs, shares, prices, total_value=10_000.0,
        cfg=CFG, cash=1_000.0, cash_band={"min": 0.10},
    )
    assert shares["MSFT"] == 0.0
    assert cash == 1_000.0 + 100 * 50


def test_entry_buys_symbol_without_target():
    # A watchlist-only name (no target_weight) is bought toward the default slot.
    shares: dict[str, float] = {}
    prices = {"ABC": 50.0}
    recs = [Recommendation(symbol="ABC", intent="Increase Exposure", reason="")]
    cash = backtest._execute(
        recs, shares, prices, total_value=100_000.0,
        cfg={"lifecycle": {"entry_default_weight": 0.05}},
        cash=100_000.0, cash_band={"min": 0.10},
    )
    assert shares["ABC"] * 50.0 == 5_000.0   # 5% of 100k
    assert cash == 95_000.0
