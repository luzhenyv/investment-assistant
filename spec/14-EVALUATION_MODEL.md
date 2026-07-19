# Evaluation Model — How Better Is Proven v1.0

> **Question this document answers:** *how do we prove one Decision, decider, or Strategy is better than another — and how is authority earned from that proof?*
> 
>It introduces **no new concepts**. Evaluation, Outcome, Decision, Strategy, and Criteria are defined in `10-ONTOLOGY`; the rule that **Evaluation measures and the human judges**, and that an **Outcome freezes once at horizon end**, are set in `11-DECISION_LOOP`. This document is the depth split out of `12-DECISION_INTELLIGENCE` §C — it says *how measurement is made honest*, and what a measured record may earn.

---

## What is measured

The unit of measurement is a **Decision** (tagged by its `actor`) and a **Strategy** (tagged by its `version`) — never a raw signal, and never an equity curve alone. A Decision is measured by binding it to the **Outcome** it produced; a Strategy is measured across the Decisions it authored.

Because engine and human emit the *same* Decision concept differing only by `actor`, one machinery measures both. "Is the engine better than me?" and "did Strategy v2 beat v1?" are **the same operation** — compare two sets of Decisions over their Outcomes.

---

## The two honesty rules

Measurement is worthless the moment it cheats. Two rules make it honest:

1. **Measure only frozen Outcomes.** An Outcome does not exist until its horizon ends (`11`). Grading a still-open position by today's mark is measuring a guess, not a result.
2. **Compare only matched Outcomes.** Two deciders or two versions may be compared *only* over the **same situations and the same horizon**. Comparing one actor's easy setups against another's hardones is not evidence — it is flattery. Matching is what turns a number into a claim.

---

## The dimensions

A Decision is never reduced to a single `hit` boolean. It is measured across dimensions, because a Decision can be right in one way and wrong in another:

| Dimension | What it measures |
|-----------|------------------|
| **Return** | realized result; realized-vs-intended |
| **Risk** | drawdown and the *path* endured to reach the return, not just the endpoint |
| **Decision quality** | precision / recall of proposals; hit-rate by kind of situation |
| **Calibration** | did stated **confidence** match realized frequency? (0.7-confidence claims should be right ~70% of the time) |
| **Explainability** | can the Decision still be traced back to the Assessments that justified it? |

**Calibration is the quiet centre.** A decider that is right often but *miscalibrated* — confident when it should be unsure — cannot be trusted with more authority, however good its returns. Calibration is how a measured record becomes a *reliable* one.

---

## What an Outcome must capture

To measure Risk honestly, an Outcome cannot be only the terminal return. It must be **path-aware**: the realized endpoint **and** the worst adverse and best favorable excursion reached over the horizon. A Decision that ended +10% after a −25% drawdown is not the same Decision as one that rose to +10% smoothly — and only a path-aware Outcome can tell them apart. *(The value stated here; how the path is computed is `architecture/BACKTEST_ENGINE`.)*

---

## Per-actor, and non-rivalrous

Every actor is measured **independently** over matched Outcomes. The system never collapses this into a single scoreboard or crowns a winner — it produces the measurements, and the **human judges** whether they are good enough (`11`). This is the discipline behind *"trust is earned, not assumed"* (`01` P4): trust is simply an accumulating, matched, per-actor record.

---

## The authority ladder

Signals earn *influence* through perspective reliability (`12` D). Deciders earn *authority* the same way — through a measured record. This is that ladder, the actor-level twin of reliability:

| Rung | What the actor may do |
|------|-----------------------|
| **report** | it is measured; it influences nothing |
| **shadow** | it proposes in parallel; every proposal is recorded; still no influence |
| **advisory** | its proposals surface to the human, who decides |
| **delegated** | it may act within a **bounded, revocable** scope — still measured |

Two rules govern the ladder, and only these two are fixed here:

- **A rung is climbed only by evidence** — a stable edge over a matched baseline, calibrated, across *enough independent* Outcomes. Climbing is earned; it is never granted, and never assumed from a short or lucky streak.
- **A rung is lost automatically** — if the edge decays or calibration drifts, authority falls without ceremony. Authority is a lease, not a title.

**Responsibility accompanies authority** (`01` P4): whoever — or whatever — holds a rung holds the accountability for it, and delegation **never removes human accountability** (`00`). The *numbers* — how many Outcomes, what significance, what scope a rung grants — are **architecture policy**, not specification; they will change as the record grows, and the White Paper must not freeze them.

---

## What breaks a measurement

Four hazards silently turn a measurement into a lie. Naming them is this document's job; *preventing* them is `architecture/BACKTEST_ENGINE`:

- **Unmatched comparison** — grading different situations against each other.
- **Survivorship** — measuring only the names that survived, so failure is invisible.
- **Peeking** — scoring an Outcome before its horizon freezes.
- **Vintage error** — measuring against history as it was *later revised*, not as it was known at `t`.

A measured record produced under any of these has not earned anything — and **no rung of the authority ladder may be climbed on it.** The ladder's honesty is only as good as the replay beneath it.

---

## First domain — equity

- **Engine vs human** on the same 20-day setups: matched Outcomes, measured per-actor across all five dimensions — including whether each party's stated confidence was calibrated.
- **Strategy v3 vs v4**: run both over the *same* historical situations; compare path-aware Outcomes, not just terminal returns.
- The engine sits at **advisory** until its matched, calibrated record over enough *independent* situations clears the bar — and it cannot clear any bar while the replay still carries survivorship (see `BACKTEST_ENGINE`).

---

## Out of scope

*How* Outcomes are computed, *how* matched sets are built, *how* the replay avoids the four hazards, and *what* the ladder's numeric thresholds are — all belong to `architecture/` (`BACKTEST_ENGINE`, and the evaluation implementation). This document fixes *what honest measurement means* and *what it may earn*; it does not choose how the numbers are produced.
