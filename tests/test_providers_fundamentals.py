"""Pure-mapper tests for the pluggable fundamentals layer (no network)."""
from quant import providers


def test_yf_and_av_map_to_same_canonical_keys():
    yf_info = {
        "sector": "Technology", "trailingPE": 56.2, "forwardPE": 9.99, "trailingPegRatio": 0.357,
        "priceToBook": 18.6, "enterpriseToEbitda": 34.6, "profitMargins": 0.415,
        "revenueGrowth": 1.963, "earningsQuarterlyGrowth": 7.7, "targetMeanPrice": 945.6,
        "beta": 2.17,
    }
    av_overview = {
        "Sector": "TECHNOLOGY", "PERatio": "53.46", "ForwardPE": "10.53", "PEGRatio": "0.357",
        "PriceToBookRatio": "17.65", "EVToEBITDA": "34.41", "ProfitMargin": "0.415",
        "QuarterlyRevenueGrowthYOY": "1.963", "QuarterlyEarningsGrowthYOY": "7.56",
        "AnalystTargetPrice": "945.6", "Beta": "2.173",
    }
    yf_c = providers._map_yf(yf_info)
    av_c = providers._map_av(av_overview)
    # Both produce exactly the canonical key set
    assert set(yf_c) == set(providers._FUND_KEYS)
    assert set(av_c) == set(providers._FUND_KEYS)
    # Spot-check a couple of mapped values
    assert yf_c["pe"] == 56.2 and yf_c["analyst_target"] == 945.6 and yf_c["peg"] == 0.357
    assert av_c["pe"] == "53.46" and av_c["analyst_target"] == "945.6"


def test_yf_peg_falls_back_to_pegRatio():
    info = {"pegRatio": 0.65}  # no trailingPegRatio
    assert providers._map_yf(info)["peg"] == 0.65


def test_yf_missing_fields_become_none():
    c = providers._map_yf({"trailingPE": 20.0})
    assert c["pe"] == 20.0
    assert c["forward_pe"] is None and c["analyst_target"] is None and c["peg"] is None


def test_fetch_fundamentals_disabled_returns_none():
    out = providers.fetch_fundamentals(["MU"], {"fundamentals": {"enabled": False}})
    assert out == {"MU": None}


def test_fetch_fundamentals_unknown_source_returns_none():
    cfg = {"fundamentals": {"enabled": True, "source": "bogus"}}
    assert providers.fetch_fundamentals(["MU"], cfg) == {"MU": None}
