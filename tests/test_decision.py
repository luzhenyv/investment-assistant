from quant import decision
from quant.models import Holding, MarketState, Signal

CFG = {
    "drift_band": 0.20,
    "scoring": {"rsi_overbought": 70, "rsi_oversold": 40, "pullback_atr_mult": 0.5},
}


def sig(symbol="X", price=100, ma50=100, ma200=90, rsi=55, pullback=False, breakout=False,
        trend=100, momentum=60):
    return Signal(
        symbol=symbol, price=price, ma20=price, ma50=ma50, ma200=ma200, rsi=rsi,
        atr=5, high_52w=price, low_52w=price * 0.5,
        trend_score=trend, momentum_score=momentum, pullback=pullback, breakout=breakout,
    )


def hold(core=10, trading=0):
    return Holding(symbol="X", core=core, trading=trading, avg_cost=50)


BULL = MarketState(regime="Bull", bull_score=70)
NEUTRAL = MarketState(regime="Neutral", bull_score=50)
PANIC = MarketState(regime="Panic", bull_score=10)
CORRECTION = MarketState(regime="Correction", bull_score=30)


def decide(s, h, mkt, cw, tw, cash_low=False, total=100000):
    return decision.decide_holding(s, h, mkt, cw, tw, total, CFG, cash_low)


def test_hedge_protects_core_in_weak_market():
    r = decide(sig(), hold(core=10), CORRECTION, cw=0.10, tw=0.10)
    assert r.intent == "Hedge"


def test_panic_add_core_when_core_zero_and_above_ma200():
    # core == 0 so hedge rule (needs core>0) does not fire; price>ma200; cash ok
    r = decide(sig(price=100, ma200=90), hold(core=0, trading=5), PANIC, cw=0.05, tw=0.10)
    assert r.intent == "Add Core"


def test_panic_no_buy_when_cash_low():
    r = decide(sig(price=100, ma200=90), hold(core=0, trading=5), PANIC,
               cw=0.05, tw=0.10, cash_low=True)
    assert r.intent == "Hold"


def test_trim_when_overweight():
    r = decide(sig(), hold(core=10), BULL, cw=0.20, tw=0.10)  # 2x target
    assert r.intent == "Trim"
    assert r.dollar_gap < 0


def test_add_core_when_underweight_and_pullback():
    r = decide(sig(pullback=True), hold(core=10), BULL, cw=0.05, tw=0.10)
    assert r.intent == "Add Core"
    assert r.dollar_gap > 0


def test_no_add_core_when_underweight_but_cash_low():
    r = decide(sig(pullback=True), hold(core=10), BULL, cw=0.05, tw=0.10, cash_low=True)
    assert r.intent == "Hold"


def test_generate_income_when_extended_at_target():
    r = decide(sig(rsi=75), hold(core=10), BULL, cw=0.10, tw=0.10)
    assert r.intent == "Generate Income"


def test_hold_is_default():
    r = decide(sig(rsi=55), hold(core=10), BULL, cw=0.10, tw=0.10)
    assert r.intent == "Hold"


def test_scan_watchlist_only_in_bull():
    signals = {"AAA": sig(symbol="AAA", breakout=True, trend=100)}
    assert decision.scan_watchlist(signals, held=set(), market=NEUTRAL) == []
    out = decision.scan_watchlist(signals, held=set(), market=BULL)
    assert len(out) == 1 and out[0].intent == "Increase Exposure"


def test_scan_watchlist_excludes_held():
    signals = {"AAA": sig(symbol="AAA", breakout=True)}
    assert decision.scan_watchlist(signals, held={"AAA"}, market=BULL) == []


def test_attach_strategy_hints():
    recs = [decision.Recommendation(symbol="X", intent="Hedge", reason="")]
    decision.attach_strategy_hints(recs, {"Hedge": ["Bear Put Spread"]})
    assert recs[0].strategy_hint == ["Bear Put Spread"]
