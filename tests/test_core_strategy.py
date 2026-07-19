"""The thin Loop slice (hermetic): Fact -> Assessment -> Decision.

Proves the first decider works, obeys the firewall, and — structurally — rests on stored Assessments
(never raw Facts, never self-produced evidence), so the explainability chain holds.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from core.assess import momentum_assessment
from core.memory import Memory
from core.record import Decision, Fact
from core.strategy import momentum_strategy

UTC = timezone.utc


def _facts(sym: str, prices: list[float], known: datetime) -> list[Fact]:
    d0 = date(2026, 1, 1)
    return [
        Fact(kind="fact", subject=sym, event_at=d0 + timedelta(days=i), known_at=known,
             provenance="test@v1", metric="close", value=p)
        for i, p in enumerate(prices)
    ]


def _decline(sym: str, known: datetime) -> list[Fact]:
    return _facts(sym, [100, 98, 96, 94, 92, 90, 88, 86, 84, 82, 80, 78, 76, 74, 72], known)


def test_slice_fact_assessment_decision(tmp_path):
    mem = Memory(tmp_path)
    known = datetime(2026, 2, 1, tzinfo=UTC)
    at = datetime(2026, 3, 1, tzinfo=UTC)
    mem.append(_decline("AAA", known))                       # Facts

    a = momentum_assessment(mem, "AAA", as_of=at)            # Fact -> Assessment (oversold)
    mem.append(a)
    d = momentum_strategy(mem, "AAA", as_of=at)              # Assessment -> Decision

    assert isinstance(d, Decision)
    assert d.actor == "engine" and d.status == "proposed"
    assert d.action == "buy"                                  # oversold -> accumulate
    assert d.refs == (a.id,)                                  # rests on the Assessment...
    assert a.refs and set(a.refs) == {f.id for f in mem.facts("AAA", "close", at)}  # ...which rests on Facts
    assert d.provenance == "momentum_strategy@v1"


def test_strategy_proposes_nothing_without_evidence(tmp_path):
    mem = Memory(tmp_path)
    mem.append(_decline("AAA", datetime(2026, 2, 1, tzinfo=UTC)))
    # Facts exist but no Assessment has been produced — a decider will not act without evidence.
    assert momentum_strategy(mem, "AAA", as_of=datetime(2026, 3, 1, tzinfo=UTC)) is None


def test_strategy_obeys_the_firewall(tmp_path):
    mem = Memory(tmp_path)
    mem.append(_decline("AAA", datetime(2026, 2, 1, tzinfo=UTC)))
    # The Assessment is made (known) on 2026-03-10.
    a = momentum_assessment(mem, "AAA", as_of=datetime(2026, 3, 10, tzinfo=UTC))
    mem.append(a)
    # A decision taken on 2026-03-05 cannot rest on a judgment not yet made -> no Decision.
    assert momentum_strategy(mem, "AAA", as_of=datetime(2026, 3, 5, tzinfo=UTC)) is None


def test_memory_roundtrips_a_decision(tmp_path):
    """The generalized store handles a third kind with no per-kind code."""
    mem = Memory(tmp_path)
    d = Decision(
        kind="decision", subject="AAA", event_at=date(2026, 3, 1),
        known_at=datetime(2026, 3, 2, tzinfo=UTC), provenance="momentum_strategy@v1",
        refs=("abc123",), actor="engine", status="proposed", action="buy",
    )
    assert mem.append(d) == 1
    got = mem.as_of(datetime(2026, 4, 1, tzinfo=UTC), "decision", "AAA")
    assert len(got) == 1
    r = got[0]
    assert (r.actor, r.status, r.action, r.refs) == ("engine", "proposed", "buy", ("abc123",))
    assert r.id == d.id                                      # identity survives the round-trip
