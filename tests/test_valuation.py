from quant import valuation

CFG = {"fundamentals": {"peg_cheap": 1.0, "peg_rich": 2.0}}


def test_num_parses_and_handles_missing():
    assert valuation._num("53.46") == 53.46
    assert valuation._num("-1.5") == -1.5
    for missing in (None, "None", "-", "", "NaN", "null", "abc"):
        assert valuation._num(missing) is None


def test_label_cheap_fair_rich_by_peg():
    assert valuation.valuation_label(20, 18, 0.5, CFG) == "cheap (growth-justified)"
    assert valuation.valuation_label(20, 18, 1.5, CFG) == "fair"
    assert valuation.valuation_label(40, 38, 3.0, CFG) == "rich"


def test_label_unknown_when_no_peg_and_no_ramp():
    assert valuation.valuation_label(None, None, None, CFG) == "unknown"
    assert valuation.valuation_label(20, 19, None, CFG) == "unknown"


def test_label_flags_forward_pe_ramp():
    # MU's case: trailing 53, forward 10.5 -> fwd << trailing note appended
    label = valuation.valuation_label(53.0, 10.5, 0.36, CFG)
    assert label.startswith("cheap (growth-justified)")
    assert "fwd PE ≪ trailing" in label


def test_label_ramp_without_peg_is_fair_not_unknown():
    label = valuation.valuation_label(53.0, 10.0, None, CFG)
    assert label == "fair · fwd PE ≪ trailing"


def test_build_computes_upside_and_fields():
    raw = {
        "Sector": "TECHNOLOGY", "PERatio": "53.46", "ForwardPE": "10.53",
        "PEGRatio": "0.357", "PriceToBookRatio": "17.65", "EVToEBITDA": "34.41",
        "ProfitMargin": "0.415", "QuarterlyRevenueGrowthYOY": "1.963",
        "QuarterlyEarningsGrowthYOY": "7.56", "AnalystTargetPrice": "945.6",
        "Beta": "2.173", "_fetched": "2026-06-22",
    }
    f = valuation.build("MU", raw, price=865.0, cfg=CFG, stale=False)
    assert f.symbol == "MU"
    assert f.sector == "TECHNOLOGY"
    assert f.pe == 53.46 and f.forward_pe == 10.53 and f.peg == 0.357
    assert f.analyst_target == 945.6
    assert abs(f.upside_to_target - (945.6 - 865.0) / 865.0) < 1e-9
    assert f.valuation_label.startswith("cheap (growth-justified)")
    assert f.as_of == "2026-06-22"
    assert f.stale is False


def test_build_handles_missing_target_and_ratios():
    raw = {"Sector": "TECHNOLOGY", "PERatio": "None", "AnalystTargetPrice": "-"}
    f = valuation.build("X", raw, price=100.0, cfg=CFG)
    assert f.pe is None
    assert f.analyst_target is None
    assert f.upside_to_target is None
    assert f.valuation_label == "unknown"
