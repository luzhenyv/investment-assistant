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


def _close_from_returns(returns):
    close = [100.0]
    for r in returns:
        close.append(close[-1] * (1.0 + r))
    return pl.Series(close)


def test_return_zscore_excludes_today_from_baseline():
    # Prior mean is exactly today's return; including today in the baseline would shift it.
    s = _close_from_returns([0.0, 0.0, 1.0, 1.0 / 3.0])
    assert abs(indicators.return_zscore(s, 3)) < 1e-12


def test_return_zscore_flags_positive_abnormal_move():
    s = _close_from_returns([-0.01, 0.0, 0.01, 0.02, 0.03, 0.04])
    assert indicators.return_zscore(s, 5) > 1.5


def test_return_zscore_flags_negative_abnormal_move():
    s = _close_from_returns([-0.01, 0.0, 0.01, 0.02, 0.03, -0.02])
    assert indicators.return_zscore(s, 5) < -1.5


def test_return_zscore_flat_or_short_history_is_zero():
    assert indicators.return_zscore(_close_from_returns([0.01, 0.01, 0.01, 0.10]), 3) == 0.0
    assert indicators.return_zscore(_close_from_returns([0.10]), 3) == 0.0


def test_atr_move_multiple_signed_close_to_close_move():
    assert indicators.atr_move_multiple(pl.Series([100.0, 103.0]), 2.0) == 1.5
    assert indicators.atr_move_multiple(pl.Series([100.0, 97.0]), 2.0) == -1.5


def test_atr_move_multiple_short_or_zero_atr_is_zero():
    assert indicators.atr_move_multiple(pl.Series([100.0]), 2.0) == 0.0
    assert indicators.atr_move_multiple(pl.Series([100.0, 103.0]), 0.0) == 0.0


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


def test_macd_divergence_bearish_negated_by_breakout():
    # Same bearish setup, but instead of fading the tail runs hard ABOVE the last swing high
    # (>80) — price has resolved the divergence to the upside, so it must read "none".
    prices = ([40] * 6 + list(range(40, 80, 2)) + list(range(80, 46, -4))
              + list(range(48, 82, 3)) + list(range(84, 120, 3)))
    assert _div_series(prices) == "none"


def test_macd_divergence_bullish_negated_by_breakdown():
    # Same bullish setup, but the tail breaks DOWN below the last swing low (<38) — the
    # selling-exhaustion thesis failed, so it must read "none".
    prices = ([80] * 6 + list(range(80, 40, -2)) + list(range(40, 74, 4))
              + list(range(72, 38, -3)) + list(range(36, 0, -3)))
    assert _div_series(prices) == "none"


def test_macd_cross():
    # Histogram sign flip between prior and current bar: negative->positive = golden,
    # positive->negative = death; same sign or no prior bar = none.
    assert indicators.macd_cross(-0.3, 0.5) == "golden"
    assert indicators.macd_cross(0.4, -0.2) == "death"
    assert indicators.macd_cross(0.4, 0.6) == "none"
    assert indicators.macd_cross(-0.4, -0.6) == "none"
    assert indicators.macd_cross(None, 0.5) == "none"   # first run / no prior bar
    assert indicators.macd_cross(0.0, 0.5) == "golden"  # crossing up off exactly zero


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
