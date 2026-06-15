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
