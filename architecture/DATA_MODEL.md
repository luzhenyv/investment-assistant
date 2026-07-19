# Data Model — The Memory v1.0

> **Layer: Architecture.** A language-independent contract. It satisfies `spec/11-DECISION_LOOP` (append-only, as-of, the temporal firewall), preserves `spec/10-ONTOLOGY`'s separations, and is the physical form of `spec/01-PHILOSOPHY` P2 (*History is Sacred*). It names no format and no code. The state of today's storage lives in `IMPLEMENTATION_STATUS.md`.
> 
> **Question this document answers:** *how does the system remember — so that anything knowable at any past instant can be read back exactly?*

---

## The Data Model is Memory

Not a store, not tables, not persisted objects. The Data Model is the system's **memory** — the reason the Vision can promise *the past is recorded, not reconstructed.* It has **one** responsibility:

> **To remember every record of the Loop, so that what was knowable at any past instant can be read back exactly — never recalled from a summary, always retrieved as it was.**

Everything below — separation, bitemporality, the reference graph, append-only — is a property memory must have to be **trustworthy**.

---

## Separate representations, never merged

Each of the 7 concepts (`10`) **SHALL** have its **own persistent representation**. Fact, Assessment,Strategy, Decision, Execution, Outcome, and Evaluation are remembered *separately*, joined only by reference — **never flattened into one.**

A memory that fuses a Fact with its Assessment cannot let a better interpretation be recomputed without disturbing the Fact — which `01` P1 forbids. **Separation in the model SHALL be separation in memory.**

---

## Bitemporal Memory

This is the one true **architecture pattern** of the system. Every record carries **two** times:

- **`event_at`** — the instant in the world it is *about* (a bar's date, an expiry, when a decision was taken);
- **`known_at`** — the instant it *became known* to the system.

They diverge whenever something arrives late or is later revised — a restated fundamental, a corrected price, a filing published after its period. Memory **SHALL** keep both, because the firewall (`11`) is defined on **`known_at`**: *judgment at `t` may read only what was `known_at ≤ t`.*

So a correction is **never an edit — it is a new record with a later `known_at`.** `as-of(t)` still returns exactly what was known then. This is the physical form of **History is Sacred** (`01` P2): the past is never overwritten by a better present. Without two times, honest replay is impossible; with them, it is true by construction.

---

## Time is protected by topology, not convention

References in memory reach **backward in `known_at` only** — a record may point solely to what was already known when it was created. The future is not a place a judgment is *asked not* to look; it is a place with **no edge leading to it.** Cheating time is impossible not because a developer remembered the rule, but because the graph offers no path to break.

> **Time is protected by topology, not convention.**

---

## The Reference Graph

Memory is an **append-only graph**. Records are addressable by identity and by (subject, `event_at`); edges are references — appended, never rewritten:

- an **Assessment** references the Facts it interpreted;
- a **Decision** references the Assessments that justified it — a human Decision also references the engine Decision it answers;
- an **Execution** references its Decision;
- an **Outcome** references the Decision it belongs to;
- an **Evaluation** references the Outcomes and the Decision/Strategy it measured.

A reference means **"this record depended on that record"** — never *"is stored inside it."* It captures **reasoning, not containment**, which is why the graph survives any storage shape: relational, document, or event log all express the same dependencies.

---

## The invariants

1. **Append-only.** Records are added, never edited or deleted; a correction is a new record. (`11`, `01` P2)
2. **As-of reconstructable.** Memory **SHALL** answer *"what was known as of `t`"* for any past `t`, keyed on `known_at`. This is the service the as-of gateway (`BACKTEST_ENGINE`) is built on.
3. **Separation preserved.** The 7 concepts are remembered distinctly, joined by reference. (`01` P1)
4. **Provenance-complete.** Every judgment (Assessment, Decision, Evaluation) **SHALL** carry enough provenance — what produced it, under which Strategy version and configuration — to be reproduced and explained. (`01` P5)

---

## What memory MUST NOT do

- edit or delete any record — a change is a new record;
- **derive history from current state** — no mutable "latest" table reconstructed by an audit log; the record *is* the history, not a byproduct of it;
- return a record whose `known_at` is after the as-of instant;
- merge two concepts into one representation;
- store a judgment without the provenance to reproduce it;
- keep only the latest value of something that changes — that silently erases the past.

---

## Out of scope

Physical format (files, tables, columns, indexes, partitioning), retention, and compaction — and *what today's storage does or does not satisfy* — belong to `IMPLEMENTATION_STATUS.md`. This contract must read the same whether memory is parquet files, a relational database, or an event log.

> **A storage engine may change. The Memory must not.**

---

## The creed

> **The Data Model does not remember the latest truth.**
> **It remembers what was known, when it was known, and why it was believed.**

*what was known* → the Fact · *when it was known* → `known_at` · *why it was believed* → the Assessment. Those are the three things a decision system may never lose.
