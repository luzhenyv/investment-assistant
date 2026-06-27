from quant import scoring


def test_trend_score_full_stack():
    # price > ma20 > ma50 > ma200 and price > ma200 -> 100
    assert scoring.trend_score(110, 105, 100, 95) == 100


def test_trend_score_broken():
    # bearish stack -> 0
    assert scoring.trend_score(90, 95, 100, 105) == 0


def test_momentum_buckets():
    assert scoring.momentum_score(75) == 80
    assert scoring.momentum_score(60) == 60
    assert scoring.momentum_score(45) == 40
    assert scoring.momentum_score(30) == 20


def test_pullback_within_band():
    # price just above ma50, within 0.5*ATR
    assert scoring.is_pullback(price=101, ma50=100, atr=10, atr_mult=0.5)
    # price too far above ma50
    assert not scoring.is_pullback(price=120, ma50=100, atr=10, atr_mult=0.5)
    # price below ma50 (not an uptrend dip)
    assert not scoring.is_pullback(price=99, ma50=100, atr=10, atr_mult=0.5)


def test_breakout():
    assert scoring.is_breakout(price=100, high_52w=100)
    assert not scoring.is_breakout(price=99, high_52w=100)


# asset_state(price, ma200, trend, rsi, pullback, breakout, accel_rsi, macd_hist, accel_macd_mode)
# Default mode is "confirm": acceleration also requires macd_hist > 0, so the accel cases pass a
# positive histogram.
def test_asset_state_broken_below_ma200():
    assert scoring.asset_state(95, 100, 100, 60, False, False, 62) == "Broken"


def test_asset_state_broken_when_trend_collapsed():
    # above MA200 but trend stack gone
    assert scoring.asset_state(105, 100, 25, 60, False, False, 62) == "Broken"


def test_asset_state_mean_reversion_takes_pullback():
    assert scoring.asset_state(105, 100, 100, 50, True, False, 62) == "Mean Reversion"


def test_asset_state_acceleration_on_breakout():
    assert scoring.asset_state(120, 100, 100, 55, False, True, 62, 1.0) == "Trend Acceleration"


def test_asset_state_acceleration_on_hot_rsi():
    assert scoring.asset_state(110, 100, 75, 65, False, False, 62, 1.0) == "Trend Acceleration"


def test_asset_state_mature_when_strong_but_not_hot():
    # strong stack, no breakout, RSI below accel threshold
    assert scoring.asset_state(110, 100, 75, 55, False, False, 62) == "Trend Mature"


def test_asset_state_range_is_default():
    assert scoring.asset_state(105, 100, 50, 55, False, False, 62) == "Range"


def test_asset_state_macd_confirm_blocks_acceleration_when_hist_negative():
    # hot RSI + strong stack but momentum rolling over (hist < 0): confirm => Mature, not accel.
    assert scoring.asset_state(110, 100, 75, 65, False, False, 62, -0.5, "confirm") == "Trend Mature"


def test_asset_state_macd_broaden_accelerates_on_positive_hist_alone():
    # No breakout, RSI below accel, but positive momentum: broaden => Acceleration.
    assert scoring.asset_state(110, 100, 75, 55, False, False, 62, 0.5, "broaden") == "Trend Acceleration"


def test_asset_state_macd_off_keeps_legacy_gate():
    # off mode ignores macd_hist entirely (legacy behavior): hot RSI alone accelerates.
    assert scoring.asset_state(110, 100, 75, 65, False, False, 62, -1.0, "off") == "Trend Acceleration"
