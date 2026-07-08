import datetime as dt

from quant import clock, manual_levels


def _data(zones, as_of=None, sym="MU", sym_as_of=None):
    entry = {"zones": zones}
    if sym_as_of is not None:
        entry["as_of"] = sym_as_of
    d = {"symbols": {sym: entry}}
    if as_of is not None:
        d["as_of"] = as_of
    return d


def test_load_missing_file_is_empty(tmp_path):
    assert manual_levels.load(str(tmp_path / "nope.yaml")) == {}


def test_path_for_sits_beside_config():
    assert manual_levels.path_for("/x/config/demo/config.yaml") == "/x/config/demo/levels.yaml"


def test_stale_fresh_vs_expired():
    today = clock.today().isoformat()
    old = (clock.today() - dt.timedelta(days=45)).isoformat()
    assert manual_levels._stale(today, 30) is False
    assert manual_levels._stale(old, 30) is True
    assert manual_levels._stale(None, 30) is True          # missing as_of → stale
    assert manual_levels._stale("not-a-date", 30) is True  # unparseable → stale


def test_zones_for_uncurated_symbol_returns_none():
    data = _data([{"low": 90, "high": 92, "strength": "strong"}], as_of=clock.today().isoformat())
    assert manual_levels.zones_for("NVDA", 100.0, data, 30) is None   # not in file
    assert manual_levels.zones_for("MU", 100.0, {}, 30) is None       # empty file


def test_zones_for_derives_kind_from_price():
    data = _data([
        {"low": 90, "high": 92, "strength": "strong"},    # below price → support
        {"low": 110, "high": 112, "strength": "medium"},  # above price → resistance
    ], as_of=clock.today().isoformat())
    zones, stale = manual_levels.zones_for("MU", 100.0, data, 30)
    assert stale is False
    kinds = {(z.low, z.high): z.kind for z in zones}
    assert kinds[(90, 92)] == "support" and kinds[(110, 112)] == "resistance"
    assert all(z.methods == ["manual"] for z in zones)
    # strongest-first ordering (strong rank 3 > medium rank 2)
    assert zones[0].label == "strong"


def test_zones_for_explicit_kind_overrides_price():
    data = _data([{"low": 90, "high": 92, "strength": "strong", "kind": "resistance"}],
                 as_of=clock.today().isoformat())
    zones, _ = manual_levels.zones_for("MU", 100.0, data, 30)
    assert zones[0].kind == "resistance"   # honoured even though band is below price


def test_zones_for_per_symbol_as_of_overrides_file():
    old = (clock.today() - dt.timedelta(days=90)).isoformat()
    data = _data([{"low": 90, "high": 92, "strength": "strong"}],
                 as_of=clock.today().isoformat(), sym_as_of=old)
    _, stale = manual_levels.zones_for("MU", 100.0, data, 30)
    assert stale is True   # symbol's own as_of (old) wins over the fresh file-level as_of


def test_zones_for_skips_malformed_entries(capsys):
    data = _data([
        {"low": 90, "high": 92, "strength": "strong"},   # good
        {"high": 92, "strength": "strong"},              # missing low → skipped
        {"low": 80, "high": 85, "strength": "huge"},      # bad strength → coerced to medium
    ], as_of=clock.today().isoformat())
    zones, _ = manual_levels.zones_for("MU", 100.0, data, 30)
    assert len(zones) == 2                                # malformed one dropped
    assert {z.label for z in zones} == {"strong", "medium"}
    assert "skipping malformed zone" in capsys.readouterr().out
