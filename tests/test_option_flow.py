from quant import option_flow
from quant.models import Zone

CFG = {"option_positioning": {"band_floor": 0.70, "band_high": 1.30,
                              "skew_pct": 0.10, "skew_warn": 0.05, "rr_good": 2.0}}


def _grid():
    """Synthetic chain around spot=100. Put OI peaks at 90, call OI peaks at 115."""
    calls = {
        90:  {"oi": 100, "vol": 10, "iv": 0.40, "price": 12.0},
        100: {"oi": 500, "vol": 200, "iv": 0.35, "price": 5.0},   # ATM
        110: {"oi": 2000, "vol": 300, "iv": 0.33, "price": 1.5},
        115: {"oi": 9000, "vol": 400, "iv": 0.34, "price": 0.8},  # call wall
    }
    puts = {
        85:  {"oi": 3000, "vol": 150, "iv": 0.55, "price": 0.7},
        90:  {"oi": 8000, "vol": 500, "iv": 0.50, "price": 1.2},  # put wall
        100: {"oi": 600, "vol": 220, "iv": 0.36, "price": 4.5},   # ATM
        110: {"oi": 80, "vol": 5, "iv": 0.32, "price": 11.0},
    }
    return {"calls": calls, "puts": puts}


def test_put_and_call_walls():
    g = _grid()
    assert option_flow.put_wall(g, 100, CFG) == 90
    assert option_flow.call_wall(g, 100, CFG) == 115


def test_walls_respect_band():
    # A huge-OI put far below the band (at 50, < 0.70*100) must be ignored.
    g = _grid()
    g["puts"][50] = {"oi": 99999, "vol": 0, "iv": 0.9, "price": 0.1}
    assert option_flow.put_wall(g, 100, CFG) == 90


def test_max_pain_is_a_band_strike():
    mp = option_flow.max_pain(_grid(), 100, CFG)
    assert mp in {85, 90, 100, 110, 115}


def test_expected_move_from_atm_straddle():
    em, em_pct = option_flow.expected_move(_grid(), 100)
    assert abs(em - (5.0 + 4.5)) < 1e-9   # ATM call + ATM put
    assert abs(em_pct - 0.095) < 1e-9


def test_pc_ratios_and_skew():
    g = _grid()
    assert option_flow.pc_oi(g) > 1.0   # more put OI than call OI here
    # skew: OTM put (~90) IV 0.50 minus OTM call (~110) IV 0.33 = +0.17
    skew = option_flow.iv_skew(g, 100, CFG)
    assert abs(skew - (0.50 - 0.33)) < 1e-9


def test_reward_risk():
    # spot 100, call wall 115 (+15% reward), put wall 90 (-10% risk) -> 1.5:1
    reward, risk, rr = option_flow.reward_risk(100, 115, 90)
    assert abs(reward - 0.15) < 1e-9
    assert abs(risk - 0.10) < 1e-9
    assert abs(rr - 1.5) < 1e-9


def test_reward_risk_handles_missing_walls():
    assert option_flow.reward_risk(100, None, 90) == (None, 0.10, None)


def test_notes_flag_confluence_and_skew():
    zones = [Zone(low=88, high=92, score=1.0, label="strong", kind="support", touches=3)]
    notes = option_flow._build_notes(
        spot=100, pw=90, cw=115, mp=100, em_low=95, em_high=105,
        rr=1.5, skew=0.17, zones=zones, cfg=CFG,
    )
    text = " ".join(notes)
    assert "confluence" in text          # put wall 90 sits inside the 88-92 support zone
    assert "expected move" in text
    assert "skew" in text                # 0.17 > skew_warn 0.05


def test_notes_warn_when_no_structural_support():
    notes = option_flow._build_notes(
        spot=100, pw=90, cw=None, mp=None, em_low=None, em_high=None,
        rr=None, skew=None, zones=[], cfg=CFG,
    )
    assert any("no structural support" in n for n in notes)
