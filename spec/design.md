# Personal US-Equity Decision System — Domain Design (SDA)

> Status: **draft for iteration**. This is the domain model (Seed-Driven Abstraction), not an
> implementation plan. The existing `quant/` code is treated as **raw material to be re-cut**, not
> settled truth.

## Purpose

A personal system that (1) preserves daily market evidence immutably, (2) interprets it into named
conditions, (3) maps those to versioned strategies and proposals, (4) records the user's actual
decision, and (5) grades — per actor, dimensionally — whether each belief was right, so trust in the
engine can be *earned*. Strategies evolve on a **PDCA loop**.

## Governing decisions

- **Autonomy** = reserved as a *graded future*. No autonomous-actor concept; `Evaluation` records
  "would the engine have been right."
- **Evaluation** = *dimensional, per-actor* (engine / agent / human). No head-to-head scorecard.
- **Screening (初筛) + web-search agent** = *runtime*, not domain concepts.
- **Sleeve** (core/trading/reserve) = an *attribute*, not a concept.
- **Position tranches / 分批建仓** = *not a stored Plan*; the ladder logic lives inside `Strategy`,
  and "planned vs filled" is *derived* from Holdings. Proposals are stateless (judged fresh).
- **Strategy** = *versioned*, PDCA-evolving.
- **Episode** = *deferred* (probe real cases before building).
- Existing code = **raw material**, freely re-shapeable.

---

## The Seed

**Observation** — an immutable, point-in-time record of *what was knowable* about one symbol at one
moment. **Raw facts only.** One responsibility: **preserve reality** (retrospection + backtest
substrate). Raw material: `data/daily_observations/<profile>/<date>.parquet`.

---

## Concept set (8 grown from the seed)

| # | Concept | One responsibility | Raw material |
|---|---------|--------------------|--------------|
| 1 | **Reading** | assert a *named condition* over Observations (RSI-oversold, golden cross, state=Mean-Reversion, valuation-fair, catalyst-pending). Recomputable; time-anchorable. | `scoring.py` state, outlier flags, `valuation.py` |
| 2 | **Lens** | a *governed source* of Observations/Readings with lifecycle `off→report→shadow→live`. The ~10 modules are instances. | `pipeline.py` `_lens` aliases |
| 3 | **Strategy** | a *versioned named policy* mapping Readings-in-context → an Intent, **including its tranche/sizing logic** (`4-3-3`, reserve discipline). Evolves via PDCA. | `decision.py` rules + `target_weights` |
| 4 | **Proposal** | a *recommended action* (Intent) for a symbol, carrying supporting Readings + Strategy version + a `sleeve` attribute (`core\|trading\|reserve`) + rationale (incl. "fills tranche 2 of 3"). Stateless; awaits a Decision. | `Recommendation` |
| 5 | **Constraint** | a *book-level gate* — block/downsize a Proposal to preserve diversification, correlation, exposure caps, reserve discipline, and the "core/trading don't mix" rule. Operates across symbols. | `gate` verb, `cash_band` |
| 6 | **Decision** | an *actor's resolution* (`engine\|agent\|human`) of a Proposal, incl. explicit no-action. Per-actor. | new (records) |
| 7 | **Execution** | *what actually transacted* vs. what was decided (catches missed/partial fills). Manual for a no-broker tool. | new (records) |
| 8 | **Evaluation** | *bind a past Proposal/Decision to realized outcome* and grade each actor dimensionally. Feeds Strategy revision (PDCA Check→Act). | `evaluate.py` |
|   | **Tracked Symbol** | a symbol with role `held\|watched` (graduates watched→held). Positions tagged by `sleeve`. | `portfolio.yaml` + `watchlist.yaml` |

### Attributes worth calling out (not concepts)
- **`sleeve`** on a position/Proposal: `core` (fundamentals+valuation) / `trading` (structure+
  discipline) / `reserve` (staged cash). "Must not mix" is a `Constraint`, not a structure.
- **Time-anchored Reading** — a valuation Reading references a *forward* fiscal window; the same
  price yields a different verdict as the window rolls (情形四). Data on the Reading.
- **Tranche state** (`planned vs filled %`) — *derived* from current Holdings + the Strategy's
  ladder, not stored. "买到 30–50% = 建仓成功" is a query, not an object.
- **Options** are subordinate: a `Sell Put` is a `Proposal` (sleeve=`core`, requires `reserve`
  cash); a `Covered Call` is an income `Proposal` on a `core` position. No option concept beyond
  "a Proposal whose instrument is an option leg."

---

## The PDCA learning loop (the spine)

```
Strategy(vN) ─Plan→ Proposal ─Do→ Decision → Execution
                                                  │
                          Evaluation ←Check───────┘
                                │
                                └─Act→ Strategy(vN+1)   ("did v2 beat v1?" is answerable)
```

`Evaluation` is per-actor and dimensional, so this loop *earns* engine trust without asserting
autonomy. Strategy versioning is what makes the "Act" measurable.

---

## Worked example — left-side scaled-entry strategy, expressed in the model

A high-vol name at a valuation floor. The `4-3-3` ladder and reserve rule live inside one
**Strategy version**; each entry is a **stateless Proposal** judged against current Readings +
derived filled%.

| Rule | Model expression |
|------|------------------|
| 分档 `4-3-3`, ratio from vol/trend/valuation/support | encoded in the **Strategy version**'s sizing logic |
| 买到 30–50% 即成功 | *derived* filled% from Holdings; `Evaluation` scores the avg-cost path, not "caught the low" |
| 情形1: 小趋势改善, 估值合理 | Readings{trend-improving, valuation-fair, structure-intact} → **Proposal** (small add, sleeve=core) |
| 情形2: 突破大结构, 估值合理 | Readings{structure-breakout, valuation-fair} → Proposal add if filled<50%; else **Hold** |
| 情形3: 快速反弹进入高估区 | Reading{valuation-rich} → **Constraint** halts core adds; a separate Proposal (sleeve=`trading`) may open with its own stop |
| 情形4: 时间推移估值重新合理 | **time-anchored Reading** rolls the forward anchor → Proposal allowed iff valuation-fair AND technical-support |
| 长线仓 vs 右侧仓 不能混 | `sleeve` attribute + **Constraint** enforcing separation |
| 可执行决策顺序 (六步) | one **Strategy version**, an ordered rule over Readings + derived filled% + sleeve |
| 现金放货基/短债, 不买计划外股票 | sleeve=`reserve` + **Constraint**: reserve cash only fills planned tranches |

All rows map with the pruned set — evidence that Position Plan and Sleeve-as-concept were *not*
needed.

---

## Concept-Test results (DELETE / SPLIT / MERGE / PRUNE)

- **SPLIT — Observation (raw, immutable) vs Reading (interpreted, recomputable).** *Biggest
  correctness fix*: improving a rule must recompute Readings over old Observations **without
  rewriting history**.
- **PRUNE — Position Plan** (folded into Strategy + derived state) and **Sleeve-as-concept**
  (demoted to an attribute). Grown only if a future strategy can't be expressed without them.
- **MERGE — Portfolio + Watchlist → Tracked Symbol**; **10 lenses → one Lens**; **三种支撑 +
  asset-state + triggers → Reading**.
- **DELETE (→ runtime) — Review** (day/week/month = one window-view over Observations + Evaluations,
  nothing stored); **Screener + web-search agent** (produce/enrich Proposals).

---

## Deferred (probe before building)

- **Episode** — the audit thread. Build only after walking 2–3 real multi-day situations shows a
  single situation genuinely spans *multiple* Proposals under one thesis. Until then, "everything
  about TSLA that week" is a query over linked records.

---

## How to validate before code

1. **Round-trip** — re-express 3 real `daily_observations` rows as Observation (raw) + N×Reading
   (interpreted); confirm no leak either way.
2. **Recompute** — regenerate one improved rule's Readings over old Observations without touching
   parquet history.
3. **Strategy fit** — express one *more* strategy (mean-reversion, swing) with no new concepts; if
   it needs one, grow it (this is the trigger to revisit Position Plan / Sleeve / Episode).
4. **Attribution** — every Proposal names its Strategy version; every Evaluation grades engine /
   agent / human independently.

## Single biggest simplification

**Review is not a concept — it's a view.** Daily / weekly / monthly collapse into one
window-parameterized query over the immutable Observation panel + Evaluation records. Nothing stored;
monthly falls out for free. The current execution plan already proved half of this by turning the
weekly report into "a pure view."
