"""The Gatherer — where `known_at` is born.

`architecture/DATA_PIPELINE.md` at seed scale: the Gatherer observes the world and records raw
**Facts**, stamping each with the instant it *first* became known. It is the only door into Memory,
and the one honest place `known_at` is assigned.

The load-bearing rule is **first-seen, not last-fetch**:
  - a genuinely new observation  → a new Fact, `known_at = now`;
  - an unchanged re-fetch        → nothing (we already knew it — `known_at` stays first-known);
  - a *changed* value (revision) → a new Fact, `known_at = now`, the old one preserved.

That last case is why this matters: yfinance fetches `auto_adjust=True`, so a split silently rewrites
history in a mutable store. Here the split arrives as an honest, dated **revision** — a new Fact — and
the past is never overwritten. The Gatherer owns this policy; the Memory just stores (separation).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable

import polars as pl

from core import clock
from core.memory import Memory
from core.record import Fact

# A Fetch turns a subject into a bar frame: columns date, open, high, low, close, volume.
Fetch = Callable[[str], "pl.DataFrame | None"]

_METRICS = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True, slots=True)
class GatherResult:
    subject: str
    new: int          # observations seen for the first time
    revised: int      # values that changed vs the current belief
    unchanged: int    # already known, identical — no record written

    @property
    def written(self) -> int:
        return self.new + self.revised


def gather(memory: Memory, subject: str, fetch: Fetch, now: datetime | None = None) -> GatherResult:
    """Observe `subject` via `fetch` and record first-seen / revised raw Facts into Memory.

    `fetch` is injected so tests use synthetic bars and only the demo touches the network.
    """
    at = now or clock.now()
    frame = fetch(subject)
    if frame is None or frame.height == 0:
        return GatherResult(subject, 0, 0, 0)

    new = revised = unchanged = 0
    to_write: list[Fact] = []
    for row in frame.sort("date").iter_rows(named=True):
        event_at: date = row["date"]
        for metric in _METRICS:
            value = row.get(metric)
            if value is None:
                continue
            value = float(value)
            prior = memory.latest_fact(subject, metric, event_at, at)
            if prior is None:
                new += 1
            elif prior.value == value:
                unchanged += 1
                continue                       # already known — first-known known_at preserved
            else:
                revised += 1                   # a revision: a new record, old one kept
            to_write.append(Fact(
                kind="fact", subject=subject, event_at=event_at, known_at=at,
                provenance="gatherer@v1", metric=metric, value=value,
            ))

    memory.append(to_write)
    return GatherResult(subject, new, revised, unchanged)


def yf_fetch(subject: str, period: str = "6mo") -> pl.DataFrame | None:
    """Live OHLCV from yfinance → polars [date, open, high, low, close, volume].

    A lean port of `quant/providers.py`'s history path (auto_adjust=True), kept here so `core/`
    never imports `quant`. Network-touching; used by the demo, never by tests.
    """
    import yfinance as yf  # local import: keeps the module importable without a network stack

    pdf = yf.Ticker(subject).history(period=period, auto_adjust=True)
    if pdf is None or pdf.empty:
        return None
    pf = pl.from_pandas(pdf.reset_index())
    date_col = "Date" if "Date" in pf.columns else pf.columns[0]
    return (
        pf.rename({date_col: "date"})
        .with_columns(pl.col("date").cast(pl.Date))
        .select(
            pl.col("date"),
            pl.col("Open").alias("open"), pl.col("High").alias("high"),
            pl.col("Low").alias("low"), pl.col("Close").alias("close"),
            pl.col("Volume").cast(pl.Float64).alias("volume"),
        )
        .drop_nulls()
    )
