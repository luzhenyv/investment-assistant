from datetime import date, timedelta

import polars as pl

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


def test_scan_watchlist_entry_rs_min_floor():
    # entry_rs_min drops laggards: a negative-RS candidate is excluded, leaving the list
    # genuinely empty rather than padded with a weak pick.
    cfg = {**CFG, "lifecycle": {"entry_rs_min": 0.0}}
    laggard = {"AAA": sig(symbol="AAA", state="Trend Acceleration", trend=100, rs=-0.058)}
    assert decision.scan_watchlist(laggard, set(), BULL, cfg, 5, 100000) == []
    # positive RS still surfaces
    good = {"BBB": sig(symbol="BBB", state="Trend Acceleration", trend=100, rs=0.20)}
    out = decision.scan_watchlist(good, set(), BULL, cfg, 5, 100000)
    assert len(out) == 1 and out[0].symbol == "BBB"


def test_scan_watchlist_max_watchlist_cap():
    # max_watchlist caps entries below the open-slot count.
    cfg = {**CFG, "lifecycle": {"max_watchlist": 2}}
    signals = {
        c: sig(symbol=c, state="Trend Acceleration", trend=100, rs=r)
        for c, r in [("A", 0.5), ("B", 0.4), ("C", 0.3), ("D", 0.2), ("E", 0.1)]
    }
    out = decision.scan_watchlist(signals, set(), BULL, cfg, 5, 100000)
    assert [r.symbol for r in out] == ["A", "B"]  # top-2 by RS, capped at max_watchlist


def _cand_pool(rs_values):
    return {
        c: sig(symbol=c, state="Trend Acceleration", trend=100, rs=r)
        for c, r in zip("ABCDEF", rs_values)
    }


def test_scan_watchlist_extra_over_slots():
    # watchlist_extra surfaces a shortlist beyond open slots for selection room.
    cfg = {**CFG, "lifecycle": {"watchlist_extra": 2, "max_watchlist": 5}}
    signals = _cand_pool([0.6, 0.5, 0.4, 0.3, 0.2, 0.1])  # 6 eligible
    out = decision.scan_watchlist(signals, set(), BULL, cfg, 3, 100000)  # 3 open slots
    assert len(out) == 5  # open_slots(3) + extra(2), under the ceiling


def test_scan_watchlist_extra_capped_by_ceiling():
    # max_watchlist caps the shortlist even when open_slots + extra would exceed it.
    cfg = {**CFG, "lifecycle": {"watchlist_extra": 2, "max_watchlist": 5}}
    signals = _cand_pool([0.6, 0.5, 0.4, 0.3, 0.2, 0.1])
    out = decision.scan_watchlist(signals, set(), BULL, cfg, 6, 100000)  # 6 open slots
    assert len(out) == 5  # min(6 + 2, 5)


def test_scan_watchlist_parabolic_note():
    # extended_ma200_mult tags an entry whose price runs far above its 200-day mean.
    cfg = {**CFG, "scoring": {**CFG["scoring"], "extended_ma200_mult": 2.0}}
    para = {"HOT": sig(symbol="HOT", state="Trend Acceleration", trend=100, rs=0.5,
                       price=300, ma200=100)}  # 3.0x MA200
    calm = {"OK": sig(symbol="OK", state="Trend Acceleration", trend=100, rs=0.5,
                      price=110, ma200=100)}   # 1.1x MA200
    assert "parabolic" in decision.scan_watchlist(para, set(), BULL, cfg, 5, 100000)[0].reason
    assert "parabolic" not in decision.scan_watchlist(calm, set(), BULL, cfg, 5, 100000)[0].reason
    # off by default (no extended_ma200_mult)
    assert "parabolic" not in decision.scan_watchlist(para, set(), BULL, CFG, 5, 100000)[0].reason


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


# --- Diversification gate (sector cap + correlation de-dup) ---------------------------

# Varying daily returns so the series has nonzero variance (constant returns => corr is
# undefined/null). A clone correlates +1 with this; the negation correlates -1.
_RETS = [0.02 if i % 3 else -0.015 for i in range(80)]


def _frame(rets):
    """Synthetic OHLC-ish price frame (date + Close) built from a daily-return series."""
    closes = [100.0]
    for r in rets:
        closes.append(round(closes[-1] * (1 + r), 4))
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(len(closes))]
    return pl.DataFrame({"date": dates, "Close": closes})


UP = _frame(_RETS)              # reference path
CLONE = _frame(_RETS)           # corr +1 with UP
ANTI = _frame([-r for r in _RETS])  # corr -1 with UP


def test_scan_watchlist_diversification_off_by_default():
    # Passing sectors/history but no knobs => identical to pure-RS ranking.
    signals = _cand_pool([0.6, 0.5, 0.4])
    sectors = {c: "Tech" for c in "ABC"}
    out = decision.scan_watchlist(signals, set(), BULL, CFG, 5, 100000, sectors=sectors)
    assert [r.symbol for r in out] == ["A", "B", "C"]


def test_scan_watchlist_sector_cap():
    cfg = {**CFG, "lifecycle": {"sector_cap": 2}}
    signals = _cand_pool([0.6, 0.5, 0.4, 0.3, 0.2])  # A..E, all Tech
    sectors = {c: "Tech" for c in "ABCDE"}
    out = decision.scan_watchlist(signals, set(), BULL, cfg, 5, 100000, sectors=sectors)
    assert [r.symbol for r in out] == ["A", "B"]  # capped at 2 per sector


def test_scan_watchlist_sector_cap_counts_holdings():
    # A held Tech name already fills one of the two sector slots.
    cfg = {**CFG, "lifecycle": {"sector_cap": 2}}
    signals = _cand_pool([0.6, 0.5, 0.4])  # A,B,C unheld
    sectors = {"A": "Tech", "B": "Tech", "C": "Tech", "OWN": "Tech"}
    out = decision.scan_watchlist(signals, {"OWN"}, BULL, cfg, 5, 100000, sectors=sectors)
    assert [r.symbol for r in out] == ["A"]  # OWN(1) + A(1) hits the cap of 2


def test_scan_watchlist_sector_label_in_scores():
    cfg = {**CFG, "lifecycle": {"sector_cap": 5}}
    signals = _cand_pool([0.6])
    out = decision.scan_watchlist(signals, set(), BULL, cfg, 5, 100000, sectors={"A": "Tech"})
    assert out[0].scores["sector"] == "Tech"


def test_scan_watchlist_unknown_sector_not_capped():
    # Names with no sector data are never sector-capped (can't confirm a cluster).
    cfg = {**CFG, "lifecycle": {"sector_cap": 1}}
    signals = _cand_pool([0.6, 0.5, 0.4])
    out = decision.scan_watchlist(signals, set(), BULL, cfg, 5, 100000, sectors={})
    assert [r.symbol for r in out] == ["A", "B", "C"]


def test_scan_watchlist_corr_dedup_within_shortlist():
    # B moves exactly like the already-kept A (different sectors, so only corr can drop it).
    cfg = {**CFG, "lifecycle": {"corr_max": 0.85, "corr_lookback": 60}}
    signals = _cand_pool([0.6, 0.5])  # A strongest, then B
    sectors = {"A": "Tech", "B": "Health"}
    history = {"A": UP, "B": CLONE}
    out = decision.scan_watchlist(signals, set(), BULL, cfg, 5, 100000,
                                  sectors=sectors, history=history)
    assert [r.symbol for r in out] == ["A"]


def test_scan_watchlist_corr_keeps_uncorrelated():
    cfg = {**CFG, "lifecycle": {"corr_max": 0.85, "corr_lookback": 60}}
    signals = _cand_pool([0.6, 0.5])  # A, B
    history = {"A": UP, "B": ANTI}  # corr -1 < 0.85 -> B survives
    out = decision.scan_watchlist(signals, set(), BULL, cfg, 5, 100000, history=history)
    assert [r.symbol for r in out] == ["A", "B"]


def test_scan_watchlist_corr_vs_current_holding():
    # A candidate redundant with a name you already own is dropped.
    cfg = {**CFG, "lifecycle": {"corr_max": 0.85, "corr_lookback": 60}}
    signals = _cand_pool([0.6])  # A only
    history = {"A": UP, "OWN": CLONE}
    out = decision.scan_watchlist(signals, {"OWN"}, BULL, cfg, 5, 100000, history=history)
    assert out == []
