# Review System — Reading the Memory v1.0

> **Layer: Architecture.** A language-independent contract. It introduces **no concept** — the White
> Paper already ruled *Review is a view, not a concept* (`12`). It composes `DATA_MODEL` (`known_at`,
> as-of), `11-DECISION_LOOP` (the firewall), and `BACKTEST_ENGINE` (the clock) — restating none. It
> names no rendering surface and no code. The state of today's reviews lives in
> `IMPLEMENTATION_STATUS.md`.
>
> **Question this document answers:** *how does the system show itself — over any window — without
> changing anything?*

---

## Responsibility

A Review System has **one** responsibility:

> **To present what the Memory already holds — over a chosen window, from a chosen vantage — without
> adding to it, judging within it, or changing it.**

A review is a **lens onto history, never a producer of it.**

> **A review adds no knowledge; it only arranges it.**

---

## A review is a view, not a concept

Review is **not** one of the 7 concepts, and it appears in **no** edge of the Loop as a producer. It is
the one operation that **only reads.** Daily, weekly, and monthly are not three things — they are **one
view with a different window.** Monthly falls out for free; there is no separate "daily review" and
"weekly review" to keep in step.

---

## Two parameters, not many reports

A review is `(window, vantage)`:

- **window** — the span of `event_at` it covers (a day, a week, a month, a quarter);
- **vantage** — the `known_at` as-of instant it reads from.

A **live** review has `vantage = now` — all current knowledge. A **historical** review has a past
vantage `t`, and **SHALL** read only records with `known_at ≤ t`, so it shows exactly what was known
*then* — "the weekly review as it would have read that Friday," not today's revisions. A review honors
the firewall exactly as replay does: it is a **Read + a window + a clock** (`BACKTEST_ENGINE`).

---

## Arrange, never judge

A review may **arrange**: select, filter, sort, count, sum, delta, rank, and compute deterministic
statistics over stored records. It **MUST NOT originate a judgment.**

A label or threshold — "abnormal", "catalyst", "priority", "overbought" — is an **Assessment**, made by
an assessor (`AGENT_ARCHITECTURE`), attributed and stored, and here only **displayed.** The line is
**belief**: arithmetic adds none; a label asserts one. A z-score is arrangement; *"abnormal"* is a
judgment. A review that invents its own labels is a **backdoor for un-recorded, un-attributed,
unmeasurable judgment** — precisely what the rest of the system exists to prevent. Judgment always has
an author; a review is not it.

---

## A review makes no Decision

A review may *arrange* open proposals — sort them by a stored urgency, group them by sleeve — but it
**MUST NOT** make or trigger a Decision. Presenting an action list is arrangement; **choosing** an
action is a Decision, and a Decision has an `actor`, never a report.

---

## A review is reproducible

A review is a **pure function of `(Memory, window, vantage)`.** The same inputs always yield the same
review; two readers at the same vantage see the same thing; there is no hidden state. This is what
makes a review **auditable** — and it is true only because the Memory beneath it is append-only and
bitemporal (`DATA_MODEL`).

---

## A dashboard is a live review

A dashboard is a review with `vantage = now`, re-read as knowledge arrives. Not a separate concept —
the same view, kept current.

---

## What a review MUST NOT do

- produce or store any record (Fact / Assessment / Decision / Outcome / Evaluation);
- **originate a judgment** — labels and thresholds are Assessments, displayed, never invented here;
- make or trigger a **Decision**;
- read **outside its declared vantage** — no later knowledge in a historical review;
- **mutate** the Memory in any way.

---

## Out of scope

Rendering (tables, charts, a web UI, a terminal, a PDF), refresh cadence, layout, and delivery
(dashboard / email / chat) — and *what today's code provides* — belong to `IMPLEMENTATION_STATUS.md`.
This contract holds whatever the surface is.

> **A review changes nothing and claims nothing. It only lets the Memory be seen.**
