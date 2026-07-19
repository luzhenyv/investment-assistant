"""The append-only, bitemporal record — the atom of the Memory.

This is `architecture/DATA_MODEL.md` made concrete, at seed scale. Every record is:

- **immutable** — a frozen dataclass; a "change" is a *new* record, never an edit;
- **bitemporal** — it carries `event_at` (the instant in the world it is *about*) and `known_at`
  (the instant it *became known* to the system). The firewall reads on `known_at`;
- **attributed** — `provenance` names what produced it, so it can be reproduced and explained;
- **referential** — `refs` lists the ids it depended on (backward in `known_at` only).

`Record` is the general shape every one of the 7 concepts will share. Only the first two subtypes
exist in the seed: `Fact` (raw environment observation) and `Assessment` (a judged interpretation).
The other five (Strategy/Decision/Execution/Outcome/Evaluation) are added the same way, later.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime


def _digest(*parts: object) -> str:
    """Deterministic short id from a record's identifying parts.

    Identical inputs → identical id (so re-importing the same observation is idempotent and the
    append-only store dedups it). Any change — a revised value, a new `known_at`, a bumped
    producer version — yields a *different* id, i.e. a new record. Identity is content, by design.
    """
    raw = "\x1f".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class Record:
    """Base: the fields every concept shares. Not stored directly — use a subtype."""

    kind: str                 # "fact" | "assessment" | ... (the concept)
    subject: str              # what it is about (e.g. a symbol)
    event_at: date            # the world instant it concerns
    known_at: datetime        # when the system first knew it (aware UTC)
    provenance: str           # producer + version, e.g. "legacy_import@v1"
    refs: tuple[str, ...] = ()  # ids this record depended on (backward in known_at only)

    @property
    def id(self) -> str:  # noqa: A003 - domain term
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class Fact(Record):
    """A raw, objective observation about the environment. Carries **no interpretation**."""

    metric: str = ""          # e.g. "close", "volume"
    value: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", "fact")

    @property
    def id(self) -> str:
        # A revision (same subject/event/metric, different value or later known_at) is a new record.
        return _digest("fact", self.subject, self.event_at, self.metric, self.value, self.known_at)


@dataclass(frozen=True, slots=True)
class Assessment(Record):
    """A judged interpretation of Facts, under a Perspective. References the Facts it read."""

    perspective: str = ""     # e.g. "momentum", "value"
    result: str = ""          # e.g. "oversold", "fair"
    confidence: float = 0.0   # 0..1

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", "assessment")

    @property
    def id(self) -> str:
        # Re-assessing with a better rule (new provenance) → new id + known_at, same Fact refs.
        return _digest(
            "assessment", self.subject, self.event_at, self.perspective,
            self.result, self.confidence, self.provenance, self.known_at,
        )


@dataclass(frozen=True, slots=True)
class Decision(Record):
    """An actor's choice, resting on Assessments. `refs` point to the Assessments that justified it —
    never to raw Facts (a decision is justified by judgment, not data). A human's answer to an engine
    proposal is a *separate* linked Decision, not an edit of it (`11-DECISION_LOOP`)."""

    actor: str = ""           # "engine" | "human"
    status: str = ""          # "proposed" | "accepted" | "rejected" | "ignored"
    action: str = ""          # "buy" | "trim" | "hold" | ...

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", "decision")

    @property
    def id(self) -> str:
        return _digest(
            "decision", self.subject, self.event_at, self.actor,
            self.status, self.action, self.provenance, self.known_at,
        )
