# Data Pipeline — Filling the Memory v1.0

> **Layer: Architecture.** A language-independent contract. It satisfies `spec/11-DECISION_LOOP` (the
> temporal firewall, append-only) and serves `DATA_MODEL` — **reusing its vocabulary** (`known_at`,
> `event_at`, the as-of gateway) and coining none. It names no source and no code. The state of today's
> pipeline lives in `IMPLEMENTATION_STATUS.md`.
>
> **Question this document answers:** *how does the outside world become Facts and Assessments the
> Memory can trust?*

---

## Responsibility

A Data Pipeline has **one** responsibility:

> **To carry the outside world into Memory — stamping each observation with the instant it became
> known, and never letting interpretation contaminate observation.**

The pipeline is the **only door into Memory.** Everything the system will ever know crosses this
threshold exactly once.

---

## The threshold — where `known_at` is born

`DATA_MODEL` *holds* `known_at`; the pipeline *assigns* it, and **nothing else may.** At the instant an
observation crosses into the system, the pipeline stamps `known_at =` the present — the honest record
of when the system first knew. A figure released today about last quarter enters with `event_at` in the
past and `known_at` today.

A pipeline **MUST NOT backdate `known_at`.** To claim knowledge earlier than the moment of crossing is
to poison every future `as-of` and every replay. `known_at` is trustworthy *because* it is set in one
place, once, at the door.

---

## Two stages, two natures

The path `source → Fact → Assessment` is not one step but two, and they differ fundamentally.

**Ingestion — world → Fact (live-only, once).** The pipeline observes a source and records a **Fact**:
raw, uninterpreted, stamped with its `event_at` and `known_at =` now, carrying its provenance. **You
cannot ingest the past** — the world is observable only in the present. A re-fetch of the same thing is
the same Fact; a *revision* is a **new** Fact with a later `known_at`, never an overwrite.

**Interpretation — Fact → Assessment (repeatable, any clock).** A later stage reads Facts and produces
**Assessments**: judgments, each stamped with its own `known_at` and the assessor and version that made
it. Interpretation is **repeatable** — a better assessor may re-read old Facts and produce a *new*
Assessment (new `known_at`), which is how understanding improves without touching history. Because an
Assessment is judgment, it obeys the firewall (`11`): it reads Facts **only through the as-of gateway**
(`DATA_MODEL`), never carving its own path to the data.

> **The past can be re-interpreted; it can never be re-observed.**
> Facts are captured once; Assessments are recomputed forever.

---

## Separation is created here

A Fact carries **no interpretation** — a source value becomes a Fact, not a verdict. The judgment that
turns it into "cheap" or "oversold" is a separate **Assessment**, in a separate record, by a named
assessor. The pipeline **MUST NOT** fuse the two: the Fact≠Assessment split (`01` P1, `DATA_MODEL`) is
either honored **at the source** or lost forever, because a Fact born entangled with a judgment can
never be cleanly separated later.

---

## Provenance is captured, never reconstructed

Provenance can only be recorded at the moment of crossing — which source, observed when, and (for an
Assessment) by which assessor version. It cannot be recovered afterward. The pipeline **SHALL** attach
it as each Fact and Assessment is created, satisfying `DATA_MODEL`'s provenance-complete invariant.
Explainability (`01` P5) begins at the door or not at all.

---

## Live and replay

Ingestion is **live-only** — it runs only on the real clock, because only the present can be observed.
Interpretation runs on **any clock**: live (stamping `known_at =` now) or replay (reproducing a past
Assessment as-of a historical `t`, reading only Facts with `known_at ≤ t` through the as-of gateway).
This is the same clock split as `BACKTEST_ENGINE` — the pipeline does not fork it, it **obeys** it.

---

## What a Data Pipeline MUST NOT do

- **backdate `known_at`** — claim knowledge earlier than the moment of crossing;
- **overwrite or mutate a Fact** on re-fetch — a revision is a new record;
- **let interpretation contaminate a Fact** — observation and judgment are separate records;
- **produce an Assessment outside the as-of gateway** — no private path to the data, no bypassing the
  firewall;
- **create a Fact or Assessment without its provenance**;
- **ingest "the past"** — the world is observable only now.

---

## Out of scope

Which sources, which parsers, fetch scheduling, retries, rate limits, caching strategy — and *what
today's pipeline does or does not satisfy* — belong to `IMPLEMENTATION_STATUS.md`. This contract holds
whatever the sources are and however they are fetched.

> **`known_at` is born at the door, once, and never moves. Everything the system can honestly claim to
> have known, it knew here first.**
