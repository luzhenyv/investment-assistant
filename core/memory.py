"""The Memory — an append-only, bitemporal, per-concept store.

`architecture/DATA_MODEL.md` at seed scale. The Memory only ever **appends**; it never edits or drops
a record. It keeps each concept in its own file (separation), stamps both `event_at` and `known_at`
(bitemporal), and answers the one question the firewall needs: *what was known as of `t`?*

Backing here is one Parquet file per kind under `root/`. That is an implementation detail
(`IMPLEMENTATION_STATUS`), not the contract — the append-only + as-of + separation semantics are what
matter, and they would hold over a database or an event log just the same.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import polars as pl

from core.record import Assessment, Fact, Record

_FACT_COLS = ["id", "subject", "event_at", "known_at", "provenance", "refs", "metric", "value"]
_ASSESS_COLS = [
    "id", "subject", "event_at", "known_at", "provenance", "refs",
    "perspective", "result", "confidence",
]


def _to_row(r: Record) -> dict:
    base = {
        "id": r.id, "subject": r.subject, "event_at": r.event_at,
        "known_at": r.known_at, "provenance": r.provenance, "refs": list(r.refs),
    }
    if isinstance(r, Fact):
        return {**base, "metric": r.metric, "value": r.value}
    if isinstance(r, Assessment):
        return {**base, "perspective": r.perspective, "result": r.result, "confidence": r.confidence}
    raise TypeError(f"unknown record type: {type(r)}")


def _from_row(kind: str, row: dict) -> Record:
    common = dict(
        subject=row["subject"], event_at=row["event_at"], known_at=row["known_at"],
        provenance=row["provenance"], refs=tuple(row["refs"]),
    )
    if kind == "fact":
        return Fact(kind="fact", metric=row["metric"], value=row["value"], **common)
    if kind == "assessment":
        return Assessment(
            kind="assessment", perspective=row["perspective"], result=row["result"],
            confidence=row["confidence"], **common,
        )
    raise ValueError(f"unknown kind: {kind}")


class Memory:
    """An append-only bitemporal store rooted at a directory."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, kind: str) -> Path:
        return self.root / f"{kind}s.parquet"

    def _read(self, kind: str) -> pl.DataFrame:
        p = self._path(kind)
        return pl.read_parquet(p) if p.exists() else pl.DataFrame()

    # -- write ---------------------------------------------------------------- #
    def append(self, records: Record | list[Record]) -> int:
        """Append records. Never edits or drops an existing row; re-appending an identical record
        (same id) is a no-op. Returns the number of genuinely new records written."""
        if isinstance(records, Record):
            records = [records]
        appended = 0
        by_kind: dict[str, list[Record]] = {}
        for r in records:
            by_kind.setdefault(r.kind, []).append(r)

        for kind, recs in by_kind.items():
            existing = self._read(kind)
            seen: set[str] = set(existing["id"].to_list()) if existing.height else set()
            new_rows = []
            for r in recs:
                if r.id in seen:
                    continue          # identical record already stored — append is idempotent
                seen.add(r.id)
                new_rows.append(_to_row(r))
            if not new_rows:
                continue
            cols = _FACT_COLS if kind == "fact" else _ASSESS_COLS
            fresh = pl.DataFrame(new_rows).select(cols)
            combined = pl.concat([existing, fresh], how="vertical") if existing.height else fresh
            combined.write_parquet(self._path(kind))
            appended += fresh.height
        return appended

    # -- read ----------------------------------------------------------------- #
    def as_of(self, t: datetime, kind: str, subject: str | None = None) -> list[Record]:
        """Every record of `kind` with `known_at <= t` — the firewall's core query. A record
        stamped after `t` is invisible, by construction."""
        df = self._read(kind)
        if not df.height:
            return []
        df = df.filter(pl.col("known_at") <= t)
        if subject is not None:
            df = df.filter(pl.col("subject") == subject)
        return [_from_row(kind, row) for row in df.iter_rows(named=True)]

    def facts(self, subject: str, metric: str, as_of: datetime) -> list[Fact]:
        """A subject's Facts for one metric, known by `as_of`, ordered by `event_at` — the honest
        history an assessor may read."""
        out = [
            f for f in self.as_of(as_of, "fact", subject)
            if isinstance(f, Fact) and f.metric == metric
        ]
        return sorted(out, key=lambda f: f.event_at)

    def latest_fact(
        self, subject: str, metric: str, event_at: date, as_of: datetime,
    ) -> Fact | None:
        """The system's *current belief* for one observation: the Fact with the greatest
        `known_at ≤ as_of` for (subject, metric, event_at), or None if never observed. A Gatherer
        uses this to tell a fresh observation from an unchanged re-fetch from a revision."""
        candidates = [
            f for f in self.as_of(as_of, "fact", subject)
            if isinstance(f, Fact) and f.metric == metric and f.event_at == event_at
        ]
        return max(candidates, key=lambda f: f.known_at) if candidates else None

    def count(self, kind: str) -> int:
        return self._read(kind).height
