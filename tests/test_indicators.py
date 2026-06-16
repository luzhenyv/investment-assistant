import polars as pl

from quant import indicators


def test_moving_average():
    s = pl.Series([1, 2, 3, 4, 5])
    assert indicators.moving_average(s, 5) == 3.0
    assert indicators.moving_average(s, 2) == 4.5


def test_rsi_all_gains_is_100():
    s = pl.Series(list(range(1, 30)))  # strictly increasing
    assert indicators.rsi(s) == 100.0


def test_rsi_midrange():
    # alternating up/down should sit near 50
    s = pl.Series([10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11])
    assert 40 <= indicators.rsi(s) <= 60


def test_atr_positive():
    high = pl.Series([11, 12, 13, 14, 15] * 4)
    low = pl.Series([9, 10, 11, 12, 13] * 4)
    close = pl.Series([10, 11, 12, 13, 14] * 4)
    assert indicators.atr(high, low, close) > 0


def test_52w_window():
    high = pl.Series(list(range(300)))  # last 252 -> max 299
    low = pl.Series(list(range(300)))
    assert indicators.high_52w(high) == 299
    assert indicators.low_52w(low) == 48  # 300-252


def test_trailing_return():
    # 100 -> 110 over a 5-bar lookback = +10%
    s = pl.Series([100.0, 102, 104, 106, 108, 110])
    assert abs(indicators.trailing_return(s, 5) - 0.10) < 1e-9


def test_trailing_return_insufficient_history_is_zero():
    s = pl.Series([100.0, 110.0])
    assert indicators.trailing_return(s, 5) == 0.0
