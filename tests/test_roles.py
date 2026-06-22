from quant import roles
from quant.models import Fundamentals, Signal

CFG = {
    "roles": {"MU": "swing", "NVDA": "core"},
    "role_rules": {
        "core_trend_min": 75,
        "core": {"horizon": "1y+", "take_profit": None, "stop_loss": None,
                 "playbook": ["CSP to enter", "Covered Call when extended"]},
        "swing": {"horizon": "weeks-months", "take_profit": 0.30, "stop_loss": 0.10,
                  "playbook": ["Buy near support", "exit +30%"]},
        "momentum": {"horizon": "days-weeks", "take_profit": 0.15, "stop_loss": 0.08,
                     "playbook": ["Shares only"]},
        "avoid": {"horizon": "—", "take_profit": None, "stop_loss": None, "playbook": ["No buys"]},
    },
}


def _sig(symbol="X", price=100.0, trend_score=80.0, state="Trend Mature"):
    return Signal(symbol=symbol, price=price, ma20=0, ma50=0, ma200=0, rsi=55, atr=2,
                  high_52w=0, low_52w=0, trend_score=trend_score, momentum_score=60,
                  pullback=False, breakout=False, state=state)


def _fund(label):
    return Fundamentals(symbol="X", sector=None, pe=None, forward_pe=None, peg=None, pb=None,
                        ev_ebitda=None, profit_margin=None, rev_growth=None, eps_growth=None,
                        analyst_target=None, beta=None, upside_to_target=None,
                        valuation_label=label, as_of="2026-06-23")


def test_suggest_core_strong_and_reasonable():
    assert roles.suggest_role(_sig(trend_score=80), _fund("cheap (growth-justified)"), CFG) == "core"
    assert roles.suggest_role(_sig(trend_score=80), _fund("fair"), CFG) == "core"


def test_suggest_momentum_strong_but_rich():
    assert roles.suggest_role(_sig(trend_score=90), _fund("rich"), CFG) == "momentum"


def test_suggest_momentum_strong_unknown_valuation():
    assert roles.suggest_role(_sig(trend_score=90), None, CFG) == "momentum"


def test_suggest_swing_on_pullback():
    assert roles.suggest_role(_sig(state="Mean Reversion", trend_score=80), _fund("fair"), CFG) == "swing"


def test_suggest_avoid_when_broken():
    assert roles.suggest_role(_sig(state="Broken", trend_score=10), _fund("cheap"), CFG) == "avoid"


def test_suggest_swing_when_weak():
    assert roles.suggest_role(_sig(trend_score=40, state="Range"), _fund("fair"), CFG) == "swing"


def test_role_plan_prices():
    plan = roles.role_plan("swing", 100.0, CFG)
    assert plan["tp_price"] == 130.0 and plan["sl_price"] == 90.0
    assert plan["horizon"] == "weeks-months"
    core = roles.role_plan("core", 100.0, CFG)
    assert core["tp_price"] is None and core["sl_price"] is None


def test_build_uses_config_role_and_flags_mismatch():
    # MU hand-set swing, but strong+rich data suggests momentum -> mismatch note
    rv = roles.build("MU", _sig(symbol="MU", trend_score=90), _fund("rich"), CFG)
    assert rv.role == "swing" and rv.source == "config"
    assert rv.suggested_role == "momentum" and rv.agree is False
    assert "confirm the thesis" in rv.note
    assert rv.tp_price == 130.0


def test_build_falls_back_to_suggestion():
    rv = roles.build("TSM", _sig(symbol="TSM", trend_score=80), _fund("cheap"), CFG)
    assert rv.source == "suggested" and rv.role == "core" and rv.agree is True
    assert rv.tp_price is None  # core has no fixed TP
