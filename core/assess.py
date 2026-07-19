"""The first Assessor — proof that Fact → Assessment is a repeatable interpretation.

An assessor reads a subject's Facts *through the Memory's as-of query* (never the future), computes
over them, and emits an **Assessment** stamped with itself + version. Improving the rule bumps the
version → a *new* Assessment (new id + `known_at`) over the *same* Facts, which is exactly how
understanding improves without touching history (`architecture/DATA_PIPELINE.md`: the past can be
re-interpreted; it can never be re-observed).

`momentum` is the seed's one assessor; more perspectives are added the same way.
"""
from __future__ import annotations

from datetime import datetime

import polars as pl

from core import clock, indicators
from core.memory import Memory
from core.record import Assessment


def momentum_assessment(
    memory: Memory,
    subject: str,
    as_of: datetime | None = None,
    *,
    oversold: float = 30.0,
    overbought: float = 70.0,
    version: str = "v1",
) -> Assessment | None:
    """Read `subject`'s close Facts known by `as_of`, and judge momentum via RSI.

    Returns None when there is too little history to judge. The `oversold`/`overbought` thresholds
    are the *rule*; changing them (and the `version`) is how the assessor improves — the test and
    the demo do exactly that to prove recompute.
    """
    at = as_of or clock.now()
    facts = memory.facts(subject, metric="close", as_of=at)
    if len(facts) < 2:
        return None

    close = pl.Series([f.value for f in facts])
    rsi = indicators.rsi(close)
    if rsi <= oversold:
        result = "oversold"
    elif rsi >= overbought:
        result = "overbought"
    else:
        result = "neutral"

    # Deterministic confidence: how far RSI sits from the neutral 50, normalized to 0..1.
    confidence = round(min(abs(rsi - 50.0) / 50.0, 1.0), 4)

    return Assessment(
        kind="assessment",
        subject=subject,
        event_at=facts[-1].event_at,          # judged as of the latest bar it read
        known_at=clock.now(),                  # when this interpretation was made
        provenance=f"momentum_assessor@{version}",
        refs=tuple(f.id for f in facts),       # the Facts this judgment rests on
        perspective="momentum",
        result=result,
        confidence=confidence,
    )
