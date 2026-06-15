import datetime as dt

import polars as pl

from quant import backtest

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
