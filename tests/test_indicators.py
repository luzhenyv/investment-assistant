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
    # alternating up/down should sit near 50 (Wilder needs a few cycles to settle)
    s = pl.Series([10.0, 11.0] * 30)
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


def test_macd_rising_series_positive_histogram():
    # A steadily accelerating series -> fast EMA above slow EMA and rising -> hist > 0.
    s = pl.Series([float(i * i) for i in range(1, 60)])
    line, signal, hist = indicators.macd(s)
    assert line > signal and hist > 0


def test_bollinger_pct_b_and_squeeze():
    # Near-flat tail (tiny vol) sits inside the band and flags a squeeze; %B in [0,1].
    s = pl.Series([100.0 + 0.01 * i for i in range(200)])
    bw, pct_b, squeeze = indicators.bollinger(s)
    assert 0.0 <= pct_b <= 1.0
    assert squeeze is True and bw >= 0.0


def _div_series(prices):
    c = pl.Series("Close", [float(x) for x in prices])
    return indicators.macd_divergence(c, c + 0.5, c - 0.5)


def test_macd_divergence_bullish():
    # Established downtrend (deep MACD low) -> strong bounce -> marginally LOWER price low
    # but a HIGHER MACD low => bullish divergence.
    prices = ([80] * 6 + list(range(80, 40, -2)) + list(range(40, 74, 4))
              + list(range(72, 38, -3)) + list(range(39, 60, 3)))
    assert _div_series(prices) == "bullish"


def test_macd_divergence_bearish():
    prices = ([40] * 6 + list(range(40, 80, 2)) + list(range(80, 46, -4))
              + list(range(48, 82, 3)) + list(range(81, 60, -3)))
    assert _div_series(prices) == "bearish"


def test_macd_divergence_none_on_clean_trend():
    assert _div_series([100 + i for i in range(60)]) == "none"
