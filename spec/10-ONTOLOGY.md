# Decision Intelligence — Ontology v1.0

> **Frozen vocabulary.** Everything downstream (Strategy Framework, Backtest, Agents, Data Pipeline, UI) uses **only these 7 words**. A new word is a *request to grow the ontology* — granted only when a real need cannot be expressed with the 7, and only after it passes the Concept Test. 
>
> This ontology is **domain-independent**. It is presented here with **US-equity investing as its first domain**; the same 7 concepts describe medical diagnosis, corporate strategy, or an autonomous agent without change.

---

## The shape: know → act → learn

```
        KNOW              ACT                        LEARN
   Fact → Assessment → Strategy → Decision → Execution → Outcome → Evaluation
            ▲                                                          │
            └──────────────── learn: reliability + Strategy(vN+1) ─────┘
```

One structural truth runs through it — an **objective → judgment** pair brackets each end:

| | objective | interpretation |
|---|---|---|
| **KNOW** (front) | Fact | Assessment |
| **LEARN** (back) | Outcome | Evaluation |

The middle three (Strategy → Decision → Execution) are the *act*. This symmetry is why all 7 concepts are real and none is redundant. The loop's **closing edge is the only feedback path**: Evaluation updates perspective reliability (→ Assessment) and drives Strategy revision (→ Strategy vN+1).

---

## The Seed

**Fact** — *an objective observation about the environment* (`NVDA closed at 180`).

Not a storage shape, and not "world-truth" — a Decision, Execution, and Outcome are *also* objective, but they are the **system's own records**, each its own concept. Fact is scoped to the **environment** so that boundary stays sharp; without it, Fact drifts toward "Thing."

---

## The 7 concepts

| # | Concept | One responsibility |
|---|---------|--------------------|
| 1 | **Fact** | preserve an objective observation about the environment |
| 2 | **Assessment** | interpret Facts into a named condition, under a **Perspective** |
| 3 | **Strategy** | map Assessments-in-context → a Decision; **versioned** |
| 4 | **Decision** | record an actor's choice |
| 5 | **Execution** | record what actually happened when a Decision met the world |
| 6 | **Outcome** | a **future Fact interpreted relative to a Decision** |
| 7 | **Evaluation** | **measure** how well a Decision/Strategy performed under given Criteria |

Attributes worth naming (qualifiers, not concepts):
- **Assessment**: `perspective`, `result`, `confidence`, optional time-anchor.
- **Decision**: `actor`, `status` (proposed \| accepted \| rejected \| ignored \| executed), `action`, `size`.

*(Which perspectives exist, and which actions/instruments are legal, is defined by each domain's Strategy Framework — the ontology does not enumerate them.)*

---

## Two invariants

1. **The look-ahead firewall — Strategy does not know Outcomes.** A Strategy may consume only Assessments; it can never read an Outcome or a future Fact. This makes look-ahead bias *unrepresentable* rather than merely discouraged.
2. **The loop is the only information flow.** Fact → Assessment → Strategy → Decision → Execution → Outcome → Evaluation → (Assessment reliability + Strategy version). Nothing skips; nothing flows backward except that single learning edge.

---

## What is *not* a concept

If a thing is one of these, it is **not** a noun in the ontology:

- **Projection** — a fold over records (e.g. current holdings = fold of Executions).
- **View** — a window query over records (e.g. any daily/weekly/monthly review).
- **Attribute** — a qualifier on a concept (e.g. a position tag, a confidence).
- **Learned value** — an output of Evaluation (e.g. how much to trust a perspective).

---

## Governing decisions

- **Autonomy = graded future.** No autonomous-actor concept. Because both engine and human emit the *same* `Decision` (differing only by `actor`), Evaluation can measure "would the engine have been right" — the evidence that could *earn* autonomy later, without building it now.
- **Evaluation is per-actor and dimensional**, never a head-to-head scorecard. It *measures*; the human *judges*.
- **Strategy is versioned**; Evaluation makes the "did v2 beat v1?" question answerable.
- **Perspective reliability is learned**, not declared — a signal earns influence through Evaluation the same way the engine earns trust.

---

## First domain — US-equity investing

The 7 concepts instantiated for equities. Everything equity-specific below is an *attribute*, *projection*, or *view* — never a new concept.

**Domain mappings**
- **Holdings / Portfolio** = a **projection** over Executions (fold of buys/sells).
- **Watchlist** = a config input (the tracked universe).
- **Perspectives** (this domain) = Value, Trend, Risk, Flow, Macro, … (defined by the equity Strategy Framework, not the ontology).
- **`sleeve`** (core / trading / reserve) and **symbol** = attributes on Decisions/positions; "core and trading must not mix" is a **risk Strategy** rule, not a structure.
- **Time-anchored valuation** = an Assessment attribute (forward window rolls; same price → different verdict, 情形四).
- **Tranche filled %** = *derived* from holdings + Strategy ("买到 30–50% = 建仓成功" is a query).
- **Options** = a Decision whose instrument is an option leg (Sell Put ⇒ sleeve=core, needs reserve cash; Covered Call ⇒ income on a core position). No option concept.
- **Screening (初筛) + web-search agent** = runtime that *produces/enriches* Assessments and Decisions.

**Worked example — left-side scaled-entry strategy in the 7 words.** The `4-3-3` ladder + reserve rule live inside **one Strategy version**; each entry is a stateless **Decision** judged against current Assessments + derived filled%.

| Rule | Expressed as |
|------|--------------|
| 分档 `4-3-3`, ratio from vol/trend/valuation/support | Strategy-version sizing logic |
| 买到 30–50% 即成功 | derived filled% from holdings (projection over Executions); Evaluation *measures* the avg-cost path |
| 情形1: 小趋势改善, 估值合理 | Assessments{trend-improving, valuation-fair, structure-intact} → Strategy → Decision(add small, sleeve=core, status=proposed) |
| 情形2: 突破大结构, 估值合理 | Assessments{structure-breakout, valuation-fair} → Decision(add if filled<50%, else Hold) |
| 情形3: 快速反弹进入高估区 | Assessment{valuation-rich} → risk Strategy halts core adds; a separate Decision(sleeve=trading) may open with its own stop |
| 情形4: 时间推移估值重新合理 | time-anchored Assessment rolls the forward anchor → Decision allowed iff valuation-fair AND technical-support |
| 长线仓 vs 右侧仓 不能混 | `sleeve` attribute + risk **Strategy** rule |
| 现金放货基/短债, 不买计划外股票 | sleeve=reserve + risk Strategy: reserve cash only fills planned tranches |

All rows map with 7 words + attributes — the proof the ontology is sufficient for this domain.

---

## Concept-Test results (SPLIT / MERGE / PRUNE / RENAME)

- **SPLIT** — Fact (objective) vs Assessment (interpretation) at the front; Outcome (objective) vs Evaluation (measurement) at the back. The two pairs are the backbone.
- **MERGE** — Proposal → `Decision(status=proposed)`; engine and human both emit `Decision`.
- **PRUNE** — Lens (→ `Assessment.perspective` + learned reliability), Constraint (→ risk Strategy), Position Plan (→ Strategy sizing), Sleeve (→ attribute), Tracked Symbol (→ symbol attribute; holdings = projection over Executions).
- **DELETE (→ view / runtime)** — Review (window view), Screener + web-search agent (runtime).
- **RENAME** — Observation → Fact (storage shape → environment truth); Reading → Assessment ("read" → "interpret"); `type` → `perspective`.

---

## Deferred (probe before building)

- **Episode** — the thread tying one situation's Facts → … → Evaluation. Build only after 2–3 real multi-step situations show a single situation genuinely spans *multiple* Decisions under one thesis. Until then it is a query over linked records.

---

## How to validate before code

1. **Round-trip** — re-express real captured records as Facts (raw) + N×Assessments (interpreted); confirm no interpretation leaks into a Fact and no raw fact hides inside an Assessment.
2. **Recompute** — regenerate an improved Assessment over old Facts **without rewriting Fact history**.
3. **Firewall** — confirm no Strategy path can read an Outcome or future Fact.
4. **Strategy fit** — express one *more* strategy (mean-reversion, swing) using only the 7 words; if it can't be, that is the signal to grow the ontology.
5. **Attribution** — every Decision names `actor` + Strategy version; every Evaluation measures engine and human independently *and* updates perspective reliability.
6. **Vocabulary freeze** — downstream docs use only the 7 words; a new noun is a request to grow the ontology, reviewed against the Concept Test.

---

## Single biggest simplification

**Only 7 things are real.** Everything else — Portfolio, tranche state, review, sleeve, signal maturity — is an *attribute*, a *projection*, a *view*, or a *learned value*. The model is **know → act → learn**, and nothing outside those 7 concepts gets to be a noun.

---

## Next document — the Decision Loop

The ontology answers *"what exists?"* The next document answers *"how does it flow?"* — the **Decision Loop**, the single permitted information path:

```
Fact → Assessment → Strategy → Decision → Execution → Outcome → Evaluation → Assessment
```

Architecture, AI, database, and agents are then defined as nothing more than *implementations of this loop* — not new concepts, not new flows.
