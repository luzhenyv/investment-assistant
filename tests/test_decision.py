from quant import decision
from quant.models import Holding, MarketState, Signal

CFG = {
    "drift_band": 0.20,
    "scoring": {"rsi_overbought": 70, "rsi_oversold": 40, "pullback_atr_mult": 0.5},
}


def sig(symbol="X", price=100, ma50=100, ma200=90, rsi=55, pullback=False, breakout=False,
        trend=100, momentum=60, state="Range", rs=0.0):
    return Signal(
        symbol=symbol, price=price, ma20=price, ma50=ma50, ma200=ma200, rsi=rsi,
        atr=5, high_52w=price, low_52w=price * 0.5,
        trend_score=trend, momentum_score=momentum, pullback=pullback, breakout=breakout,
        state=state, rs=rs,
    )


def hold(core=10, trading=0):
    return Holding(symbol="X", core=core, trading=trading, avg_cost=50)


BULL = MarketState(regime="Bull", bull_score=70)
NEUTRAL = MarketState(regime="Neutral", bull_score=50)
PANIC = MarketState(regime="Panic", bull_score=10)
CORRECTION = MarketState(regime="Correction", bull_score=30)


def decide(s, h, mkt, cw, tw, cash_low=False, total=100000):
    return decision.decide_holding(s, h, mkt, cw, tw, total, CFG, cash_low)


def test_close_when_broken():
    r = decide(sig(state="Broken"), hold(core=10), BULL, cw=0.10, tw=0.10)
    assert r.intent == "Close"
    assert r.dollar_gap < 0


def test_close_precedes_hedge_in_weak_market():
    # Broken + weak regime: exit beats hedge (Close sits above the Hedge rule).
    r = decide(sig(state="Broken"), hold(core=10), CORRECTION, cw=0.10, tw=0.10)
    assert r.intent == "Close"


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


def test_no_trim_when_accelerating_below_ceiling():
    # Overweight vs base target (0.15 > 0.12 band) but within the raised accel
    # ceiling (0.10*1.2*1.5 = 0.18) => add to strength, not trim.
    r = decide(sig(state="Trend Acceleration"), hold(core=10), BULL, cw=0.15, tw=0.10)
    assert r.intent == "Add Core"
    assert r.dollar_gap > 0


def test_trim_when_accelerating_above_ceiling():
    # Past the raised ceiling (0.20 > 0.18) => trim even though accelerating.
    r = decide(sig(state="Trend Acceleration"), hold(core=10), BULL, cw=0.20, tw=0.10)
    assert r.intent == "Trim"


def test_pyramid_add_is_one_step():
    # Staged: add one step (target/max_steps = 0.10/3), not the full gap to ceiling.
    r = decide(sig(state="Trend Acceleration"), hold(core=10), BULL, cw=0.10, tw=0.10,
               total=100000)
    assert r.intent == "Add Core"
    assert abs(r.dollar_gap - (0.10 / 3) * 100000) < 1e-6


def test_no_pyramid_when_cash_low():
    r = decide(sig(state="Trend Acceleration"), hold(core=10), BULL, cw=0.10, tw=0.10,
               cash_low=True)
    assert r.intent != "Add Core"


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


def scan(signals, held, mkt, slots, total=100000):
    return decision.scan_watchlist(signals, held, mkt, CFG, slots, total)


def test_scan_watchlist_skips_weak_regimes():
    signals = {"AAA": sig(symbol="AAA", state="Trend Acceleration", trend=100)}
    assert scan(signals, set(), CORRECTION, 5) == []
    out = scan(signals, set(), NEUTRAL, 5)
    assert len(out) == 1 and out[0].intent == "Increase Exposure"


def test_scan_watchlist_admits_trend_mature():
    signals = {"AAA": sig(symbol="AAA", state="Trend Mature", trend=80, rs=0.3)}
    out = scan(signals, set(), BULL, 5)
    assert len(out) == 1 and out[0].symbol == "AAA"


def test_scan_watchlist_excludes_held():
    signals = {"AAA": sig(symbol="AAA", state="Trend Acceleration")}
    assert scan(signals, {"AAA"}, BULL, 5) == []


def test_scan_watchlist_ranks_by_relative_strength():
    # Weaker state but higher RS should outrank a strong state with lower RS.
    signals = {
        "AAA": sig(symbol="AAA", state="Trend Acceleration", trend=100, rs=0.10),
        "BBB": sig(symbol="BBB", state="Trend Mature", trend=80, rs=0.50),
        "CCC": sig(symbol="CCC", state="Mean Reversion", trend=90, rs=0.30),
    }
    out = scan(signals, set(), BULL, 2)
    assert [r.symbol for r in out] == ["BBB", "CCC"]  # ranked by rs, capped at slots


def test_scan_watchlist_entry_is_one_step():
    # Entry buys a first scale-in step (default slot 0.05 / max_steps 3 of 100k).
    signals = {"AAA": sig(symbol="AAA", state="Trend Acceleration", trend=100, rs=0.2)}
    out = scan(signals, set(), BULL, 5, total=100000)
    assert abs(out[0].dollar_gap - (0.05 / 3) * 100000) < 1e-6


def test_scan_watchlist_entry_threshold():
    # trend below entry_trend_min (75) is excluded even in an entry state.
    signals = {"AAA": sig(symbol="AAA", state="Mean Reversion", trend=50)}
    assert scan(signals, set(), BULL, 5) == []


def test_scan_watchlist_zero_slots():
    signals = {"AAA": sig(symbol="AAA", state="Trend Acceleration", trend=100)}
    assert scan(signals, set(), BULL, 0) == []


def rotate(signals, held, weights, mkt, cash_low=True, total=100000):
    return decision.rotation(signals, held, weights, mkt, CFG, total, cash_low)


def test_rotation_trims_laggard_to_fund_best():
    signals = {
        "WIN": sig(symbol="WIN", state="Trend Mature", trend=80, rs=0.50),
        "LAG": sig(symbol="LAG", state="Trend Mature", trend=80, rs=0.05),
    }
    out = rotate(signals, {"LAG"}, {"LAG": 0.10}, BULL)
    assert [r.intent for r in out] == ["Trim", "Increase Exposure"]
    assert out[0].symbol == "LAG" and out[0].dollar_gap < 0   # exit first
    assert out[1].symbol == "WIN" and out[1].dollar_gap > 0


def test_rotation_closes_deeply_weak_laggard():
    signals = {
        "WIN": sig(symbol="WIN", state="Trend Acceleration", trend=100, rs=0.40),
        "LAG": sig(symbol="LAG", state="Range", trend=60, rs=-0.10),
    }
    out = rotate(signals, {"LAG"}, {"LAG": 0.08}, BULL)
    assert out[0].intent == "Close" and out[0].symbol == "LAG"
    assert out[0].dollar_gap == -0.08 * 100000


def test_rotation_skips_when_margin_not_met():
    signals = {
        "WIN": sig(symbol="WIN", state="Trend Mature", trend=80, rs=0.12),
        "LAG": sig(symbol="LAG", state="Trend Mature", trend=80, rs=0.08),
    }
    assert rotate(signals, {"LAG"}, {"LAG": 0.10}, BULL) == []  # 0.04 gap < 0.10 margin


def test_rotation_never_sells_accelerating_winner():
    signals = {
        "WIN": sig(symbol="WIN", state="Trend Mature", trend=80, rs=0.50),
        "HOT": sig(symbol="HOT", state="Trend Acceleration", trend=100, rs=0.05),
    }
    # the only held name is accelerating -> excluded from laggards -> no rotation
    assert rotate(signals, {"HOT"}, {"HOT": 0.10}, BULL) == []


def test_rotation_off_when_cash_not_low():
    signals = {
        "WIN": sig(symbol="WIN", state="Trend Mature", trend=80, rs=0.50),
        "LAG": sig(symbol="LAG", state="Trend Mature", trend=80, rs=0.05),
    }
    assert rotate(signals, {"LAG"}, {"LAG": 0.10}, BULL, cash_low=False) == []


def test_attach_strategy_hints():
    recs = [decision.Recommendation(symbol="X", intent="Hedge", reason="")]
    decision.attach_strategy_hints(recs, {"Hedge": ["Bear Put Spread"]})
    assert recs[0].strategy_hint == ["Bear Put Spread"]
