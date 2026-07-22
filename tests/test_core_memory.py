"""Seed proof (hermetic) — the honest Memory's three claims, on synthetic Facts.

These are the P0 architecture claims made testable:
  1. as-of firewall — a record stamped after `t` is invisible to `as_of(t)`;
  2. separation — a Fact carries no interpretation; an Assessment references Facts;
  3. recompute / append-only — improving a rule adds a new Assessment over UNTOUCHED Facts.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import polars as pl

from core.assess import momentum_assessment
from core.memory import Memory
from core.record import Assessment, Fact

UTC = timezone.utc


def _close_fact(sym: str, day: date, price: float, known: datetime) -> Fact:
    return Fact(
        kind="fact", subject=sym, event_at=day, known_at=known,
        provenance="test@v1", metric="close", value=price,
    )


def _series(sym: str, prices: list[float], known: datetime) -> list[Fact]:
    d0 = date(2026, 1, 1)
    return [_close_fact(sym, d0 + timedelta(days=i), p, known) for i, p in enumerate(prices)]


def test_append_only_and_idempotent(tmp_path):
    mem = Memory(tmp_path)
    f = _close_fact("AAA", date(2026, 1, 1), 100.0, datetime(2026, 1, 2, tzinfo=UTC))
    assert mem.append(f) == 1
    assert mem.append(f) == 0          # same id -> no-op, nothing dropped or duplicated
    assert mem.count("fact") == 1


def test_append_accepts_older_parquet_without_payload(tmp_path):
    known = datetime(2026, 1, 2, tzinfo=UTC)
    old = _close_fact("AAA", date(2026, 1, 1), 100.0, known)
    pl.DataFrame([{
        "id": old.id,
        "kind": old.kind,
        "subject": old.subject,
        "event_at": old.event_at,
        "known_at": old.known_at,
        "provenance": old.provenance,
        "refs": [],
        "metric": old.metric,
        "value": old.value,
    }]).write_parquet(tmp_path / "facts.parquet")

    mem = Memory(tmp_path)
    new = _close_fact("AAA", date(2026, 1, 2), 101.0, known)

    assert mem.append(new) == 1
    assert mem.count("fact") == 2
    assert "payload" in pl.read_parquet(tmp_path / "facts.parquet").columns


def test_as_of_firewall(tmp_path):
    mem = Memory(tmp_path)
    early = datetime(2026, 1, 2, tzinfo=UTC)
    late = datetime(2026, 6, 1, tzinfo=UTC)
    mem.append(_close_fact("AAA", date(2026, 1, 1), 100.0, early))
    mem.append(_close_fact("AAA", date(2026, 5, 1), 120.0, late))

    # A vantage between the two known_at instants sees only the earlier record.
    seen = mem.as_of(datetime(2026, 3, 1, tzinfo=UTC), "fact", "AAA")
    assert [f.value for f in seen] == [100.0]
    # A vantage before anything was known sees nothing.
    assert mem.as_of(datetime(2026, 1, 1, tzinfo=UTC), "fact", "AAA") == []


def test_fact_has_no_interpretation():
    f = _close_fact("AAA", date(2026, 1, 1), 100.0, datetime(2026, 1, 2, tzinfo=UTC))
    # A Fact exposes metric/value only — no perspective/result/confidence anywhere on it.
    assert f.metric == "close" and f.value == 100.0
    assert not hasattr(f, "result") and not hasattr(f, "perspective")


def test_assessment_references_facts(tmp_path):
    mem = Memory(tmp_path)
    known = datetime(2026, 2, 1, tzinfo=UTC)
    facts = _series("AAA", [100, 98, 96, 94, 92, 90, 88, 86, 84, 82, 80, 78, 76, 74, 72], known)
    mem.append(facts)
    a = momentum_assessment(mem, "AAA", as_of=datetime(2026, 3, 1, tzinfo=UTC))
    assert isinstance(a, Assessment)
    assert a.perspective == "momentum"
    assert a.result == "oversold"                      # a monotonic decline -> low RSI
    assert set(a.refs) == {f.id for f in facts}         # rests on exactly those Facts


def test_recompute_leaves_facts_untouched(tmp_path):
    mem = Memory(tmp_path)
    known = datetime(2026, 2, 1, tzinfo=UTC)
    facts = _series("AAA", [100, 101, 103, 104, 106, 108, 110, 113, 116, 118, 121, 124, 127, 130, 133],
                    known)
    mem.append(facts)
    at = datetime(2026, 3, 1, tzinfo=UTC)

    facts_before = pl.read_parquet(mem._path("fact"))

    a1 = momentum_assessment(mem, "AAA", as_of=at, overbought=70, version="v1")
    mem.append(a1)
    # A stricter rule (v2) is a different producer -> a NEW assessment over the SAME facts.
    a2 = momentum_assessment(mem, "AAA", as_of=at, overbought=60, version="v2")
    mem.append(a2)

    facts_after = pl.read_parquet(mem._path("fact"))
    assert facts_before.equals(facts_after)             # history byte-identical: never rewritten
    assert a1.id != a2.id and set(a1.refs) == set(a2.refs)
    assert mem.count("assessment") == 2                 # both interpretations preserved
