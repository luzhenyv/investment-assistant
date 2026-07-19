"""Gatherer proof (hermetic) — `known_at` is born at the door, first-seen not last-fetch.

Uses an injected fake fetch (no network). The four cases are the ingestion contract of
`architecture/DATA_PIPELINE.md`: new observation, unchanged re-fetch, revision, and honest
composition with the legacy importer.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import polars as pl

from core.gather import gather
from core.memory import Memory
from core.record import Fact

UTC = timezone.utc


def _bars(rows: list[tuple[date, float, float, float, float, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows, schema=["date", "open", "high", "low", "close", "volume"], orient="row",
    )


def _fetch(frame: pl.DataFrame):
    return lambda _subject: frame


def test_first_gather_stamps_known_at_now(tmp_path):
    mem = Memory(tmp_path)
    now = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)
    frame = _bars([
        (date(2026, 3, 1), 10.0, 11.0, 9.5, 10.5, 1000.0),
        (date(2026, 3, 2), 10.5, 12.0, 10.0, 11.8, 1200.0),
    ])
    res = gather(mem, "AAA", _fetch(frame), now=now)
    assert (res.new, res.revised, res.unchanged) == (10, 0, 0)   # 2 bars × 5 metrics
    assert mem.count("fact") == 10
    assert all(f.known_at == now for f in mem.as_of(now, "fact", "AAA"))
    assert all(f.provenance == "gatherer@v1" for f in mem.as_of(now, "fact", "AAA"))


def test_regather_identical_is_noop(tmp_path):
    mem = Memory(tmp_path)
    frame = _bars([(date(2026, 3, 1), 10.0, 11.0, 9.5, 10.5, 1000.0)])
    gather(mem, "AAA", _fetch(frame), now=datetime(2026, 3, 2, tzinfo=UTC))
    # A later re-fetch of identical data writes nothing; first-known known_at is preserved.
    res2 = gather(mem, "AAA", _fetch(frame), now=datetime(2026, 3, 9, tzinfo=UTC))
    assert (res2.new, res2.revised, res2.unchanged) == (0, 0, 5)
    assert mem.count("fact") == 5
    close = mem.latest_fact("AAA", "close", date(2026, 3, 1), datetime(2026, 4, 1, tzinfo=UTC))
    assert close.known_at == datetime(2026, 3, 2, tzinfo=UTC)     # not re-stamped


def test_revision_appends_new_fact_keeps_old(tmp_path):
    mem = Memory(tmp_path)
    day = date(2026, 3, 1)
    t1 = datetime(2026, 3, 2, tzinfo=UTC)
    t2 = datetime(2026, 6, 1, tzinfo=UTC)          # e.g. after a split re-adjusts history
    gather(mem, "AAA", _fetch(_bars([(day, 10.0, 11.0, 9.5, 10.5, 1000.0)])), now=t1)
    res = gather(mem, "AAA", _fetch(_bars([(day, 10.0, 11.0, 9.5, 5.25, 1000.0)])), now=t2)  # close halved
    assert res.revised == 1 and res.unchanged == 4                # only close changed
    # Old close Fact preserved; current belief reflects the revision.
    closes = [f for f in mem.as_of(t2, "fact", "AAA") if f.metric == "close"]
    assert len(closes) == 2
    assert mem.latest_fact("AAA", "close", day, t2).value == 5.25
    # As of BEFORE the revision, the belief is still the original.
    assert mem.latest_fact("AAA", "close", day, t1).value == 10.5


def test_sub_cent_difference_is_unchanged(tmp_path):
    mem = Memory(tmp_path)
    day = date(2026, 3, 1)
    gather(mem, "AAA", _fetch(_bars([(day, 10.0, 11.0, 9.5, 10.5000, 1000.0)])),
           now=datetime(2026, 3, 2, tzinfo=UTC))
    # A rounded/full-precision difference below a cent is the SAME observation, not a revision.
    res = gather(mem, "AAA", _fetch(_bars([(day, 10.0, 11.0, 9.5, 10.5001, 1000.0)])),
                 now=datetime(2026, 3, 9, tzinfo=UTC))
    assert res.revised == 0 and res.unchanged == 5
    assert mem.count("fact") == 5


def test_cent_level_change_is_revision(tmp_path):
    mem = Memory(tmp_path)
    day = date(2026, 3, 1)
    gather(mem, "AAA", _fetch(_bars([(day, 10.0, 11.0, 9.5, 10.50, 1000.0)])),
           now=datetime(2026, 3, 2, tzinfo=UTC))
    # A genuine one-cent move is a real revision — the tolerance masks noise, not real change.
    res = gather(mem, "AAA", _fetch(_bars([(day, 10.0, 11.0, 9.5, 10.51, 1000.0)])),
                 now=datetime(2026, 3, 9, tzinfo=UTC))
    assert res.revised == 1 and res.unchanged == 4


def test_composes_with_legacy_known_at(tmp_path):
    mem = Memory(tmp_path)
    day = date(2026, 3, 1)
    # A value already known from the legacy panel, at an earlier known_at.
    mem.append(Fact(
        kind="fact", subject="AAA", event_at=day, known_at=datetime(2026, 3, 2, 1, 0, tzinfo=UTC),
        provenance="legacy_import@v1", metric="close", value=10.5,
    ))
    # A live gather of the SAME value later is unchanged — the two producers reconcile honestly.
    res = gather(mem, "AAA", _fetch(_bars([(day, 10.0, 11.0, 9.5, 10.5, 1000.0)])),
                 now=datetime(2026, 3, 9, tzinfo=UTC))
    closes = [f for f in mem.as_of(datetime(2026, 4, 1, tzinfo=UTC), "fact", "AAA")
              if f.metric == "close"]
    assert len(closes) == 1                                        # no duplicate for the same value
    assert closes[0].provenance == "legacy_import@v1"             # first-known wins
    assert res.new == 4 and res.unchanged == 1                    # OHL+V new, close already known
