from datetime import date, timedelta

import polars as pl

from quant import evaluate


def _bars(closes, start=date(2026, 6, 1)):
    """Ascending daily bars (weekend gaps don't matter — the evaluator counts positions, not dates)."""
    return pl.DataFrame({
        "date": [start + timedelta(days=i) for i in range(len(closes))],
        "Close": [float(c) for c in closes],
    })


def test_forward_returns_positional_horizon():
    # close doubles every step: +1 bar = +100%, +2 bars = +300%.
    bars = _bars([10, 20, 40, 80, 160])
    r = evaluate.forward_returns(bars, "2026-06-01", horizons=(1, 2, 4))
    assert r[1] == 1.0
    assert r[2] == 3.0
    assert r[4] == 15.0


def test_forward_returns_counts_trading_days_not_calendar():
    # 5 sequential bars; asking +3 from the first must land on the 4th bar (position, not date math).
    bars = _bars([100, 101, 102, 103, 110])
    r = evaluate.forward_returns(bars, "2026-06-01", horizons=(3,))
    assert abs(r[3] - (103 / 100 - 1)) < 1e-12


def test_forward_returns_none_when_window_incomplete():
    bars = _bars([100, 105, 110])  # only 2 bars ahead of the first
    r = evaluate.forward_returns(bars, "2026-06-01", horizons=(2, 5, 20))
    assert r[2] is not None
    assert r[5] is None and r[20] is None


def test_forward_returns_none_when_session_absent():
    bars = _bars([100, 105, 110])
    assert evaluate.forward_returns(bars, "2025-01-01", horizons=(1,))[1] is None


def test_grade_long_intents():
    assert evaluate.grade("Add Core", 0.05) is True
    assert evaluate.grade("Increase Exposure", -0.02) is False


def test_grade_reduce_intents_reward_avoided_drawdown():
    assert evaluate.grade("Close", -0.08) is True   # it fell → closing was right
    assert evaluate.grade("Trim", 0.04) is False    # it rose → trimming was wrong


def test_grade_hold_within_band():
    assert evaluate.grade("Hold", 0.01) is True
    assert evaluate.grade("Hold", 0.05) is False    # moved beyond ±3%


def test_grade_ungraded_intents_and_missing_return():
    assert evaluate.grade("Generate Income", 0.10) is None
    assert evaluate.grade("Hedge", -0.10) is None
    assert evaluate.grade("", 0.10) is None
    assert evaluate.grade("Add Core", None) is None


def test_summarize_groups_and_base_rate():
    graded = [
        {"state": "Trend Acceleration", "intent": "Add Core",
         "fwd": {5: 0.10}, "hit": {5: True}},
        {"state": "Trend Acceleration", "intent": "Add Core",
         "fwd": {5: 0.00}, "hit": {5: False}},
        {"state": "Broken", "intent": "Close",
         "fwd": {5: -0.20}, "hit": {5: True}},
    ]
    rows, base = evaluate.summarize(graded, "state", horizons=(5,))
    assert abs(base[5] - (0.10 + 0.00 - 0.20) / 3) < 1e-12
    accel = next(r for r in rows if r["key"] == "Trend Acceleration")
    assert accel[5]["n"] == 2
    assert abs(accel[5]["mean"] - 0.05) < 1e-12
    assert accel[5]["hit_rate"] == 0.5
