# Roadmap — From Assistant to Earned Autonomy v1.0

> **Layer: Project (living).** Not a contract — a **plan**. It knows the code and sequences the work to
> close the gap between what the six architecture contracts require and what the code does today. It
> **cites** the contracts and `IMPLEMENTATION_STATUS`, never restates them. Unlike the spec, this file
> is *expected to change*: as a phase lands, its gaps move `☐→✅` and this doc is rewritten.
>
> **Question this document answers:** *what do we build, in what order, and why — to get from today to
> the Vision?*

---

## The headline truth

Today the system sits at the **bottom** of `14`'s authority ladder: nothing is earned. The reason is
**not a shortage of features.** It is that the two foundations that make any record *honest* do not yet
exist — so no measurement can be trusted, so nothing can be earned. This roadmap is not a feature
list; it is the honest **order in which trust becomes possible.**

## The one dependency that orders everything

Every status section across the six contracts converged on the same root:

> **There is no `known_at` axis, and the seven record types are fused.**

From that single fact, two whole classes of dishonesty follow:

- you cannot ask *"what was known as of `t`"* → no honest as-of, replay, or measurement
  (`DATA_MODEL`, `DATA_PIPELINE`, `BACKTEST_ENGINE`, `REVIEW_SYSTEM`);
- you cannot attribute a judgment to its author → no honest per-actor comparison, no decider isolation
  (`AGENT_ARCHITECTURE`).

Fix those two and the rest is downhill. Skip them and everything above is built on sand.

---

## The phases

### P0 · The honest Memory — the store rebuild
*(closes `DATA_MODEL`; the vantage half of `BACKTEST_ENGINE` / `REVIEW_SYSTEM`)*

- **Bitemporal** — every record carries `event_at` + `known_at`.
- **Append-only** — stop overwriting on rerun and re-fetch; a correction is a *new* record.
- **Separation** — Fact / Assessment / Decision / Execution / Outcome / Evaluation become distinct
  records joined by reference; dissolve the wide observations row.

*Unblocks:* as-of, replay, honest measurement — **everything.**

### P1 · The honest producers — the ingestion & attribution rebuild
*(closes `DATA_PIPELINE`; the separation/attribution of `AGENT_ARCHITECTURE`)*

- Pipeline **splits ingestion** (world→Fact: stamps `known_at`, never overwrites, records provenance)
  **from interpretation** (Fact→Assessment via the as-of gateway).
- Agents get **roles** (Gatherer / Assessor / Decider) and every output is **attributed** (agent +
  version).
- **Decider isolated from its evidence** — split assessment out of `decision.py`'s path.

*Unblocks:* honest attribution → per-actor measurement.

### P2 · Honest measurement — make the record trustworthy
*(closes `BACKTEST_ENGINE` limitations; `14`'s measurement clauses)*

- **One as-of gateway** + a conformance test that *fails* on any read with time > `t`.
- **Path-aware Outcomes** (terminal + max adverse/favorable excursion), frozen at horizon.
- **Per-actor, calibrated Evaluation** — not engine-only hit-rate.
- **Point-in-time universe** (kill survivorship) + **slippage**.

*Unblocks:* a record honest enough to *earn* on.

### P3 · The ladder turns — begin earning
*(activates `14`'s ladder; closes `REVIEW_SYSTEM`)*

- The engine runs in **shadow**, accumulating a matched per-actor record beside the human.
- **Reviews made pure** — move outlier / catalyst / priority judgments into assessors as stored
  Assessments; split `daily_review`'s producing from reviewing; add the `known_at` vantage.
- The engine climbs **report → shadow → advisory** *only* as its calibrated, matched record clears the
  bar.

### P4 · Breadth — now cheap, because the contracts hold

- More **Strategy** instances against the one interface: mean-reversion, swing, right-side/momentum,
  options overlays, risk/diversification.
- **Assessor and research agents** as role-bound, attributed producers: the AI screener (初筛),
  web-research to confirm/refute — none bypassing the firewall or the ladder.

> These were the voice log's **first** asks. They land near the **end** because they are worthless on a
> dishonest record and trivial on an honest one.

### P5 · Earned autonomy — conditional
*(the Vision's destination; gated by P0–P3)*

- A decider reaches **delegated** — acting within a **bounded, revocable** scope — **iff** its
  measured, calibrated, matched record clears the bar over enough *independent* Outcomes.
- **Responsibility stays human** even when authority is delegated (`00`, `01` P4).
- If the record **never** clears the bar, the system stays advisory forever — **and that is a success,
  not a failure.** It means the honest answer was *"don't."*

This is the ordered, gated answer to *"assistant → autonomous"*: not a switch, a summit reached only
over an honest climb.

---

## What this reorders from the original Vision

The voice log's first instinct was **features** — a screener, more strategies, eventual autonomy. The
roadmap inverts it:

> **Features are P4. Foundations are P0.**

Everything the original ask wanted is still here — it just sits *on top of* the honesty machinery that
makes it worth having. Building P4 before P0 is exactly the *dishonest learning* the Vision exists to
prevent.

---

## Where we are

| Phase | Status |
|-------|--------|
| P0 · Honest Memory | ☐ not started — **the critical path** |
| P1 · Honest producers | ☐ |
| P2 · Honest measurement | ◐ decision *logic* is point-in-time clean; data vintage + calibration owed |
| P3 · The ladder turns | ☐ |
| P4 · Breadth | ☐ (lenses/skills exist as report-only precursors) |
| P5 · Earned autonomy | ☐ (gated) |

The current per-phase gaps are itemised in `IMPLEMENTATION_STATUS.md`. This table is rewritten as they
close — **a stale roadmap is worse than none.**
