"""The first Strategy — a decider that maps Assessments to a proposed Decision.

A Strategy is a **producer**, like an assessor: the seed does not store it as a record (a Decision
references it by provenance). It becomes a stored record only when Evaluation needs to compare versions.

Two `architecture/AGENT_ARCHITECTURE.md` rules are enforced here **structurally**, not by comment:

- **A decider may not produce the evidence it consumes.** This function reads Assessments *from the
  Memory* and imports no assessor — it physically cannot fabricate its own justification.
- **Justify only with Assessments.** It reads Assessments (never raw Facts), and the Decision's `refs`
  point at the Assessment it rested on — so the explainability chain is Decision → Assessment → Fact.

And, like every judgment, it obeys the firewall: it reads only `as_of` its decision instant.
"""
from __future__ import annotations

from datetime import datetime

from core import clock
from core.memory import Memory
from core.record import Assessment, Decision

# Momentum reading -> proposed action. Oversold = accumulate, overbought = trim, neutral = stand pat.
_ACTION = {"oversold": "buy", "overbought": "trim", "neutral": "hold"}


def momentum_strategy(
    memory: Memory, subject: str, as_of: datetime | None = None, *, version: str = "v1",
) -> Decision | None:
    """Read `subject`'s latest momentum Assessment known by `as_of`, and propose a Decision.

    Returns None when there is no momentum Assessment to rest on — a Strategy may propose nothing
    (`11-DECISION_LOOP`), and it will not act without evidence.
    """
    at = as_of or clock.now()
    candidates = [
        a for a in memory.as_of(at, "assessment", subject)
        if isinstance(a, Assessment) and a.perspective == "momentum"
    ]
    if not candidates:
        return None
    assessment = max(candidates, key=lambda a: a.known_at)   # the current momentum belief
    action = _ACTION.get(assessment.result, "hold")

    return Decision(
        kind="decision",
        subject=subject,
        event_at=assessment.event_at,
        known_at=at,                            # decided at the judgment instant (= now, live; = t, replay)
        provenance=f"momentum_strategy@{version}",
        refs=(assessment.id,),          # rests on the Assessment — never the raw Facts
        actor="engine",
        status="proposed",
        action=action,
    )
