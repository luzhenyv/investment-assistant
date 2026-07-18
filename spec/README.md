# Specification & Architecture — Structure & Checklist (v1.0)

> This file is the **index and memo** for the docs. It does not define anything — it says *which doc
> answers which question, in what order, and what each may not do*. It never re-defines the Ontology.

## Organizing principle

**Language → Behavior → Implementation.** Stabilize in that order. The vocabulary (Ontology) is
frozen first; behavior (the Loop) next; only then may implementation evolve freely. A doc earlier in
this chain must never depend on one later in it.

## The two layers

| Layer | Folder | Nature | Changes when… |
|-------|--------|--------|---------------|
| **Specification** (White Paper) | `spec/` | The stable contract | …the *domain* is understood differently (rare) |
| **Architecture** | `architecture/` | The implementation | …the *tech/scale* changes (often) |

`architecture/` is a **top-level sibling** of `spec/`, not nested under it.

## Three rules every doc obeys

1. **One doc, one question.** If a doc answers two questions, it is two docs.
2. **No doc re-defines the Ontology.** Docs *reference* the 7 words; only `10-ONTOLOGY` defines them.
3. **A new noun is a request to grow the Ontology.** Any new domain noun must pass the Concept Test
   in `10-ONTOLOGY` before it may appear elsewhere.

---

## Layer 1 — Specification (White Paper) · 5 docs

| Doc | Question it answers | Must **not** | Status |
|-----|--------------------|--------------|--------|
| `00-VISION.md` | *Why does this system exist?* — problem, goals, non-goals, long-term vision | prescribe design or tech | ☐ pending |
| `01-PHILOSOPHY.md` | *Why is it designed this way?* — Fact vs Assessment, immutable Facts, PDCA, explainability, evolution-over-completion, human-in-the-loop; cites **SDA** | list concepts (that's `10`) | ☐ pending |
| `10-ONTOLOGY.md` | *What exists?* — the 7 concepts | describe flow or implementation | ☑ **done** → `spec/ontology.md` |
| `11-DECISION_LOOP.md` | *How do the concepts flow?* — lifecycle, who-generates-whom, who-depends-on-whom, **forbidden edges** | add new concepts | ☑ **done** → `spec/11-DECISION_LOOP.md` |
| `12-DECISION_INTELLIGENCE.md` | *How does the system know, choose, and improve?* — Knowledge Model + Strategy Framework + Evaluation Model + Learning | re-define the Loop | ☐ pending — **write next** |

**`11-DECISION_LOOP` — the forbidden edges it must state explicitly:**
- Strategy **cannot** read Outcome or any future Fact (the look-ahead firewall).
- Evaluation **cannot** mutate Fact (Facts are immutable).
- The **only** feedback edge is Evaluation → {Assessment perspective-reliability, Strategy version}.

**`12-DECISION_INTELLIGENCE` — the split criterion (SDA watch).** This doc deliberately merges three
questions (knowledge shape / what a Strategy is / how to prove one better). Keep it merged **only
while each stays a cleanly separable section answering one question.** The moment a section needs to
reference another to be understood, or the doc stops being scannable, split it back into
`12-KNOWLEDGE_MODEL` / `13-STRATEGY_FRAMEWORK` / `14-EVALUATION_MODEL`. Merging is the default;
splitting is pre-authorized by this rule.

---

## Layer 2 — Architecture (evolving) · implementation only

Each answers *"how do we implement the spec?"* — none is domain truth. Existing `docs/` files are
raw material to fold in, not authorities.

| Doc | Question | Raw material in repo |
|-----|----------|----------------------|
| `DATA_MODEL.md` | How does the Ontology persist? (Fact store, Decision fields, indexes) | `docs/DATA_FLYWHEEL.md`, `data/daily_observations/` |
| `DATA_PIPELINE.md` | How do Facts arrive? (source → parse → Fact → Assessment) | `quant/pipeline.py`, `quant/providers.py` |
| `AGENT_ARCHITECTURE.md` | What do agents do? (fact-extraction, assessment, research, strategy-selection) | `.claude/skills/*`, `quant/` lenses |
| `BACKTEST_ENGINE.md` | How is the Loop replayed? (Fact→Assessment→Decision→Outcome, **not** re-running Strategy blindly) | `backtest.py`, `quant/backtest.py` |
| `REVIEW_SYSTEM.md` | Daily/weekly/monthly views + dashboard (all **views**, no new concepts) | `daily_review.py`, `weekly_review.py` |
| `API.md` | External surface | — |
| `DEPLOYMENT.md` | Runtime, scheduling, storage | `quant/clock.py`, cron |
| `docs/ARCHITECTURE.md`, `docs/STRATEGY_ENGINE.md` | (existing) | reconcile → the docs above |

---

## Writing order & dependencies

```
01-PHILOSOPHY ─┐
00-VISION ─────┼→ 10-ONTOLOGY ✅ → 11-DECISION_LOOP → 12-DECISION_INTELLIGENCE → (architecture/*)
               └  (00/01 anchor the rest; safe to write in parallel with 11)
```

`10` is done. **`11` is the critical path** — it's where the firewall becomes structurally
enforceable, so it gates `12` and everything in `architecture/`.

---

## Open decisions

- **Naming convention.** Current file is `spec/ontology.md` (flat). Recommend numeric prefixes
  (`00-`, `01-`, `10-`, `11-`, `12-`) so the folder sorts in reading order; rename
  `ontology.md → 10-ontology.md` when convenient. Cosmetic, not urgent.
- **`12` merge vs split.** Merged by default; split governed by the criterion above.

---

## Checklist / 备忘

**Foundation**
- ☐ `00-VISION.md` — problem · goals · non-goals · long-term vision
- ☐ `01-PHILOSOPHY.md` — design rationale, cite SDA (immutable Facts, PDCA, human-in-the-loop, evolution-over-completion)

**Domain (White Paper)**
- ☑ `10-ONTOLOGY.md` — frozen 7 concepts (`spec/ontology.md`)
- ☑ `11-DECISION_LOOP.md` — flow + forbidden edges (firewall, append-only, single feedback edge)
- ☐ `12-DECISION_INTELLIGENCE.md` — knowledge + strategy + evaluation + learning (watch the split criterion)

**Architecture (evolving)** — begin only after `11`
- ☐ `DATA_MODEL` · ☐ `DATA_PIPELINE` · ☐ `AGENT_ARCHITECTURE` · ☐ `BACKTEST_ENGINE` · ☐ `REVIEW_SYSTEM` · ☐ `API` · ☐ `DEPLOYMENT`
- ☐ reconcile existing `docs/ARCHITECTURE.md` + `docs/STRATEGY_ENGINE.md` into the above

**Project**
- ☐ `99-ROADMAP.md`

**Invariants to check on every doc**
- ☐ answers exactly one question
- ☐ uses only the 7 Ontology words (a new noun → Concept Test first)
- ☐ references the Ontology, never redefines it
- ☐ nothing earlier in Language→Behavior→Implementation depends on something later
