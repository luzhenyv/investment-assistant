# Backtest Engine — Replaying the Loop v1.0

> **Layer: Architecture.** An implementation of the specification, and replaceable. It **satisfies** `spec/11-DECISION_LOOP` (the temporal firewall, append-only) and **serves** `spec/14-EVALUATION_MODEL` (honest, path-aware Outcomes). It restates neither, and it names no code. The state of today's implementation lives in `IMPLEMENTATION_STATUS.md`, which may change without touching this contract.
> 
> **Question this document answers:** *how is the Decision Loop replayed over history to produce Outcomes — without cheating time?*

---

## Responsibility

A Replay Engine has **one** responsibility:

> **To reconstruct every historical Decision Loop exactly as it could have happened at that time.** Nothing more. Nothing less.

Everything below is a constraint that responsibility implies.

---

## Replay is a clock, not a system

The Decision Loop (`11`) is **clock-agnostic**. It does not know whether "now" is today or a decade ago — it reads records with time ≤ `t` and acts at `t`. Change what supplies `t`, and the *same* Loop runs live or over history:

```
                 Decision Loop
                      │
                 ┌────┴────┐
                 │  Clock  │
                 └────┬────┘
              ┌───────┴────────┐
        Historical Clock    Real Clock
           (Replay)           (Live)
```

**Replay = Decision Loop + Historical Clock. Live = Decision Loop + Real Clock.** Replay is not a second system that imitates the first; it is the *same* Loop with a different clock provider. In one line:

> **History changes only the clock.**

---

## Single Decision Path

It follows that replay and live execution **SHALL share one Decision Path.** There is exactly one engine. A replay that runs a *copy* of the decision logic measures the copy, not the system — so its record would be a record of a fiction. The engine that acts in the world and the engine replayed over history MUST be reached through the same path; only the clock differs.

---

## The temporal firewall

To satisfy `11`'s firewall — *judgment at `t` may read only the ≤ t era* — a replay implementation:

- **SHALL** expose a **single as-of gateway**: every read a judgment (Assessment, Strategy, Decision) performs passes through one interface that yields only records with time ≤ `t`.
- **SHALL** execute no earlier than the next instant after `t` — a Decision made at `t` acts at `t⁺`, never on the same bar.
- **SHALL** carry a **conformance test that fails** if any judgment path can obtain a record with time `t`.

A Strategy that could reach past the gateway is not a bug to be found later; it is a firewall that does not exist.

---

## Producing Outcomes

Replay produces an **Outcome** for each Decision through an **Outcome Provider**. The Outcome:

- **SHALL** be **path-aware** (`14`): the realized endpoint *and* the worst-adverse / best-favorable excursion over the horizon — never terminal-only, or Risk cannot be measured.
- **SHALL** be **frozen once**, at horizon end (`11`), and never revised.
- **SHALL** bind to the Decision it belongs to, so measurement can join them.

*How* the provider computes the path is implementation; *that* it is path-aware and frozen is contract.

---

## Feeding Evaluation

Replay emits the engine's Decisions and their Outcomes; the human's Decisions come from the live append-only record. Per-actor measurement (`14`) is the **matched join** of the two over the same situations. Replay's duty is only to *produce matchable, frozen Outcomes* — the measuring is `14`'s.

---

## Point-in-time data

Replay is only as honest as the data it reads. A replay implementation **SHALL** read **point-in-time data** — prices, fundamentals, and *universe membership* as they were known at `t`, not as later revised. Where point-in-time data cannot be supplied, the implementation:

- **SHALL** declare the bias in every result it produces — an optimistic number MUST never be mistaken for skill; and
- **MUST NOT** let any decider climb the authority ladder (`14`) above **shadow** on a record built from non-point-in-time data.

This is the same promise `14` makes from the other side: *a rung is earned only on an honest record.* Point-in-time data is what makes the record honest.

---

## What a replay MUST NOT do

The contract, mirroring `11`'s invariants and `14`'s hazards. A replay implementation MUST NOT:

- expose any record with time > `t` to a judgment;
- execute on the same instant a Decision was made;
- surface an Outcome before its horizon freezes;
- measure against a silently-revised data vintage;
- replay only the survivors.

---

## Out of scope

*How* the clock, the as-of gateway, and the Outcome Provider are built — and *what* today's code already satisfies or still owes — belong to `IMPLEMENTATION_STATUS.md`, which ages with the code. This document is the contract a replay must meet **in any language or architecture**; it should read the same after a rewrite from Python to anything else.
