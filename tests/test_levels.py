from datetime import date, timedelta

import polars as pl

from quant import levels
from quant.levels import _Candidate
from quant.models import Zone

# Minimal config mirroring config/demo/config.yaml's `levels:` block defaults.
LEV = {
    "levels": {
        "pivot_k": 2, "lookback_bars": 0, "box_win": 4, "box_pct": 0.06,
        "fib_ratios": [0.382, 0.5, 0.618], "cluster_pct": 0.015, "cluster_atr_mult": 1.0,
        "touch_cap": 5, "confluence_bonus": 0.35, "volume_bins": 40, "volume_node_mult": 1.3,
        "weights": {"kind": 1.0, "duration": 1.0, "touch": 0.8, "reaction": 0.6,
                    "volume": 1.0, "method": 1.0},
        "method_prior": {"fib": 1.0, "swing": 1.0, "box": 0.8, "volume": 0.9, "ma": 0.5, "round": 0.4},
        "label_quantiles": {"super_strong": 0.90, "strong": 0.65, "medium": 0.30},
    }
}


def _frame(closes, vols=None):
    n = len(closes)
    dates = pl.date_range(date(2020, 1, 1), date(2020, 1, 1) + timedelta(days=n - 1), "1d", eager=True)
    cols = {
        "date": dates,
        "Open": [float(c) for c in closes],
        "High": [float(c) + 1 for c in closes],
        "Low": [float(c) - 1 for c in closes],
        "Close": [float(c) for c in closes],
    }
    if vols is not None:
        cols["Volume"] = [float(v) for v in vols]
    return pl.DataFrame(cols)


def _cand(price, method, score=1.0, is_point=True):
    c = _Candidate(price, price, price, method, is_point, 1, "daily")
    c.score = score
    return c


# --- _to_weekly --------------------------------------------------------------
def test_to_weekly_aggregates():
    daily = _frame(list(range(14)))  # 14 calendar days
    weekly = levels._to_weekly(daily)
    assert weekly.height < daily.height
    # max High / min Low preserved across the resample
    assert weekly["High"].max() == daily["High"].max()
    assert weekly["Low"].min() == daily["Low"].min()


# --- swing pivots ------------------------------------------------------------
def test_swing_pivot_detects_peak_and_trough():
    # clear peak at index 4 (value 20), trough at index 8 (value 2)
    closes = [10, 12, 15, 18, 20, 14, 9, 5, 2, 6, 11, 15]
    cands = levels._swing_pivots(_frame(closes), k=2, bar_days=1, atr=2.0, timeframe="daily")
    prices = [round(c.price) for c in cands]
    assert 21 in prices  # peak High = 20 + 1
    assert 1 in prices   # trough Low = 2 - 1


# --- clustering --------------------------------------------------------------
def test_cluster_merges_near_and_splits_far():
    cands = [_cand(100, "swing"), _cand(100.5, "fib"), _cand(130, "swing")]
    zones = levels._cluster(cands, LEV["levels"], atr=1.0, price=120)
    assert len(zones) == 2
    merged = [z for z in zones if z.low <= 100 <= z.high][0]
    assert merged.members == 2


def test_confluence_rewards_distinct_methods():
    same = levels._cluster([_cand(100, "swing"), _cand(100, "swing"), _cand(100, "swing")],
                           LEV["levels"], atr=1.0, price=120)
    diverse = levels._cluster([_cand(100, "swing"), _cand(100, "fib"), _cand(100, "volume")],
                              LEV["levels"], atr=1.0, price=120)
    assert len(same) == 1 and len(diverse) == 1
    assert diverse[0].score > same[0].score


# --- labeling ----------------------------------------------------------------
def test_label_quantile_buckets():
    # strong_min_methods=1 isolates pure quantile bucketing from the confluence cap.
    lev = {**LEV["levels"], "strong_min_methods": 1}
    zones = levels._cluster([_cand(p, "swing", score=float(p)) for p in range(1, 11)],
                            lev, atr=0.001, price=5)
    # tiny atr -> each candidate its own zone, scores 1..10
    levels._label_zones(zones, lev)
    by_score = {round(z.score): z.label for z in zones}
    assert by_score[10] == "super-strong"
    assert by_score[1] == "small"


def test_low_confluence_zone_capped_at_medium():
    # a 2-method zone with the dominant score is still capped (strong_min_methods=3 default).
    cands = [_cand(100, "swing", 50), _cand(100, "fib", 50)] + [_cand(p, "swing", 1.0) for p in (60, 70, 80)]
    zones = levels._cluster(cands, LEV["levels"], atr=1.0, price=120)
    levels._label_zones(zones, LEV["levels"])
    top = max(zones, key=lambda z: z.score)
    assert len(top.methods) == 2 and top.label == "medium"


# --- volume ------------------------------------------------------------------
def test_volume_profile_poc():
    # 30 bars parked at 100 (heavy volume) + scattered light-volume bars elsewhere
    closes = [100] * 30 + [80, 85, 90, 110, 115, 120, 95, 105, 88, 112]
    vols = [1000] * 30 + [10] * 10
    nodes = levels._volume_profile(_frame(closes, vols), bar_days=1, lev=LEV["levels"], timeframe="daily")
    assert all(n.method == "volume" for n in nodes)
    # the POC (highest-volume node) should sit at the 100 cluster
    poc = max(nodes, key=lambda n: n.volume)
    assert poc.low <= 100 <= poc.high


def test_polarity_flip_rule():
    assert levels._flipped(95, 105, max_close=120, min_close=80, band=5)   # closed both sides
    assert not levels._flipped(95, 105, max_close=120, min_close=98, band=5)  # never below
    assert not levels._flipped(95, 105, max_close=108, min_close=80, band=5)  # never above


def test_value_area_expands_around_poc():
    # symmetric profile peaked at the centre bin -> value area brackets it
    bins = [1.0, 2.0, 5.0, 10.0, 5.0, 2.0, 1.0]
    val, vah = levels._value_area(bins, poc=3, frac=0.70)
    assert val < 3 < vah and val >= 0 and vah <= 6


def test_anchored_vwap():
    closes = list(range(100, 140))            # uptrend
    cands = levels._anchored_vwap(_frame(closes, [1000] * 40), 1, LEV["levels"], 5.0, "daily")
    assert cands and all(c.method == "vwap" for c in cands)
    assert all(99 <= c.price <= 140 for c in cands)  # within the frame's price range
    # no Volume column -> no vwap candidates
    assert levels._anchored_vwap(_frame(closes), 1, LEV["levels"], 5.0, "daily") == []


def test_volume_agnostic_path():
    closes = [10, 12, 15, 18, 20, 14, 9, 5, 2, 6, 11, 15, 19, 22, 17, 12, 8, 14, 20, 25]
    ohlc_only = levels.detect_zones(_frame(closes), LEV)
    assert ohlc_only  # produces zones without a Volume column, no crash
    assert all("volume" not in z.methods for z in ohlc_only)
    assert all(len(z.methods) >= 2 for z in ohlc_only)  # confluence filter (min_methods=2)
    with_vol = levels.detect_zones(_frame(closes, [100] * len(closes)), LEV)
    assert with_vol  # runs with Volume present too


def _zone(low, high, kind, label="strong", methods=("fib", "swing", "volume")):
    return Zone(low=low, high=high, score=1.0, label=label, kind=kind, touches=1,
                methods=list(methods))


def test_nearest_zones_picks_closest_each_side():
    zones = [
        _zone(80, 82, "support"), _zone(90, 92, "support"),   # nearest support = 90–92
        _zone(110, 112, "resistance"), _zone(120, 122, "resistance"),  # nearest resist = 110–112
    ]
    sup, res = levels.nearest_zones(100.0, zones)
    assert (sup.low, sup.high) == (90, 92)
    assert (res.low, res.high) == (110, 112)


def test_nearest_zones_price_none_uses_kind():
    # With price=None it ranks by kind alone: highest-high support, lowest-low resistance.
    zones = [_zone(80, 82, "support"), _zone(90, 92, "support"),
             _zone(110, 112, "resistance"), _zone(120, 122, "resistance")]
    sup, res = levels.nearest_zones(None, zones)
    assert (sup.low, sup.high) == (90, 92)
    assert (res.low, res.high) == (110, 112)


def test_nearest_zones_missing_side_returns_none():
    sup, res = levels.nearest_zones(100.0, [_zone(90, 92, "support")])
    assert sup is not None and res is None
    assert levels.nearest_zones(100.0, []) == (None, None)
