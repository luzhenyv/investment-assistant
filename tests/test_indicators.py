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


# --- extended indicator library (ported from stockstats) ------------------- #
def _ohlc(closes):
    """Build (high, low, close) Series from a close path (±1 synthetic range)."""
    c = pl.Series("Close", [float(x) for x in closes])
    return c + 1.0, c - 1.0, c


def test_roc_exact():
    c = pl.Series([100.0, 102, 104, 106, 108, 110])  # 100 -> 110 over 5 bars
    assert abs(indicators.roc(c, 5) - 10.0) < 1e-9


def test_cmo_all_gains_is_100():
    c = pl.Series([float(x) for x in range(1, 40)])  # strictly up -> no down sum
    assert abs(indicators.cmo(c) - 100.0) < 1e-9


def test_obv_accumulates_on_up_days():
    c = pl.Series([float(x) for x in range(1, 11)])  # 9 up-days
    v = pl.Series([100.0] * 10)
    assert indicators.obv(c, v) == 900.0


def test_aroon_strong_uptrend():
    h, l, _ = _ohlc(range(1, 41))  # last bar is the window high; window low is oldest
    assert indicators.aroon(h, l, 25) == 96.0  # up 100 - down 4


def test_kdj_range_and_uptrend():
    h, l, c = _ohlc(range(1, 40))
    k, d, _ = indicators.kdj(h, l, c)
    assert 0.0 <= k <= 100.0 and 0.0 <= d <= 100.0
    assert k > 80  # close pinned at the window high


def test_adx_uptrend_di_dominates():
    h, l, c = _ohlc(range(1, 60))
    adx_v, pdi, ndi = indicators.adx(h, l, c)
    assert adx_v >= 0 and pdi >= 0 and ndi >= 0
    assert pdi > ndi  # clean uptrend -> +DI leads


def test_williams_r_range():
    h, l, c = _ohlc([10, 12, 11, 13, 15, 14, 16, 18, 17, 19] * 3)
    assert -100.0 <= indicators.williams_r(h, l, c) <= 0.0


def test_mfi_range():
    h, l, c = _ohlc([10, 12, 11, 13, 15, 14, 16, 18, 17, 19] * 3)
    assert 0.0 <= indicators.mfi(h, l, c, pl.Series([1000.0] * 30)) <= 100.0


def test_stoch_rsi_range():
    c = pl.Series([10.0, 11, 10.5, 12, 13, 12.5, 14, 15, 14.5, 16] * 4)
    assert 0.0 <= indicators.stoch_rsi(c) <= 100.0


def test_cci_positive_in_uptrend():
    h, l, c = _ohlc(range(1, 40))
    assert indicators.cci(h, l, c) > 0


def test_trix_is_finite():
    t = indicators.trix(pl.Series([float(x) for x in range(1, 60)]))
    assert t == t  # not NaN


def test_supertrend_direction_and_line():
    h, l, c = _ohlc(range(1, 40))
    line, direction = indicators.supertrend(h, l, c)
    assert direction in (-1.0, 0.0, 1.0)
    assert line > 0


def test_kama_within_price_bounds():
    kama = indicators.kama(pl.Series([float(x) for x in range(1, 40)]))
    assert 1.0 <= kama <= 39.0
