"""Import raw Facts from the legacy wide-row panel into the Memory.

The old `data/daily_observations/<profile>/*.parquet` panel fuses raw observation with interpretation
in one row. This importer extracts **only the raw environment observations** — the OHLCV of each bar —
as Facts. It deliberately ignores the interpreted columns (`state`, `intent`, `reason`): those are
Assessments/Decisions, and the seed *regenerates* them from Facts to prove the split holds.

Bitemporality comes straight from the panel: `bar_date` → `event_at` (the market day), `create_time`
→ `known_at` (when the system first recorded that bar, post-close). It is an honest approximation —
many bars in one run share a `create_time` — good enough to prove the mechanism; a live pipeline
stamps a truer `known_at` later.
"""
from __future__ import annotations

import glob
from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl

from core.memory import Memory
from core.record import Fact

# Panel column -> Fact metric. `price` is the panel's name for the close.
_METRICS = {"open": "open", "high": "high", "low": "low", "price": "close", "volume": "volume"}


def _parse_known_at(s: str) -> datetime:
    """'2026-07-18 01:54:02 UTC' -> aware UTC datetime."""
    return datetime.strptime(s.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _rows_to_facts(df: pl.DataFrame) -> list[Fact]:
    facts: list[Fact] = []
    for row in df.iter_rows(named=True):
        subject = row["symbol"]
        event_at = date.fromisoformat(row["bar_date"])
        known_at = _parse_known_at(row["create_time"])
        for col, metric in _METRICS.items():
            v = row.get(col)
            if v is None:
                continue
            facts.append(Fact(
                kind="fact", subject=subject, event_at=event_at, known_at=known_at,
                provenance="legacy_import@v1", metric=metric, value=float(v),
            ))
    return facts


def import_panel(memory: Memory, panel_glob: str) -> int:
    """Read every daily panel file matching `panel_glob`, emit raw OHLCV Facts, append to Memory.
    Returns the number of new Facts stored. Idempotent (the Memory dedups by id)."""
    files = sorted(f for f in glob.glob(panel_glob) if "__weekly" not in Path(f).name)
    keep = ["symbol", "bar_date", "create_time", *_METRICS]
    appended = 0
    for f in files:
        df = pl.read_parquet(f)
        have = [c for c in keep if c in df.columns]
        appended += memory.append(_rows_to_facts(df.select(have)))
    return appended
