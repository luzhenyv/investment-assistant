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

## Layer 1 — Specification (White Paper) · 6 docs

| Doc | Question it answers | Must **not** | Status |
|-----|--------------------|--------------|--------|
| `00-VISION.md` | *Why does this system exist?* — problem, goals, non-goals, long-term vision | prescribe design or tech | ☑ **done** → `spec/00-VISION.md` |
| `01-PHILOSOPHY.md` | *Why is it designed this way?* — Fact vs Assessment, immutable Facts, PDCA, explainability, evolution-over-completion, human-in-the-loop; cites **SDA** | list concepts (that's `10`) | ☑ **done** → `spec/01-PHILOSOPHY.md` |
| `10-ONTOLOGY.md` | *What exists?* — the 7 concepts | describe flow or implementation | ☑ **done** → `spec/ontology.md` |
| `11-DECISION_LOOP.md` | *How do the concepts flow?* — lifecycle, who-generates-whom, who-depends-on-whom, **forbidden edges** | add new concepts | ☑ **done** → `spec/11-DECISION_LOOP.md` |
| `12-DECISION_INTELLIGENCE.md` | *How does the system know, choose, and improve?* — Knowledge + Strategy + Learning (§C Evaluation **split out** to `14`) | re-define the Loop | ☑ **done** → `spec/12-DECISION_INTELLIGENCE.md` (§C now a pointer) |
| `14-EVALUATION_MODEL.md` | *How is "better" proven, and how is authority earned?* — dimensions, matched/per-actor Outcomes, the authority ladder | fix numeric thresholds (arch) | ☑ **done** → `spec/14-EVALUATION_MODEL.md` |

**`11-DECISION_LOOP` — the forbidden edges it must state explicitly:**
- Strategy **cannot** read Outcome or any future Fact (the look-ahead firewall).
- Evaluation **cannot** mutate Fact (Facts are immutable).
- The **only** feedback edge is Evaluation → {Assessment perspective-reliability, Strategy version}.

**`12`→`14` split (done).** Evaluation's lifecycle diverged first (per-actor matched Outcomes,
calibration, the authority ladder), so §C was split out to `14-EVALUATION_MODEL` and `12`§C reduced to
a pointer. Knowledge and Strategy remain merged in `12` until *their* lifecycles diverge — the same
evolution-rate trigger (not length) would later split `12-KNOWLEDGE_MODEL` / `13-STRATEGY_FRAMEWORK`.

---

## Layer 2 — Architecture (evolving) · implementation only

Each answers *"how do we implement the spec?"* — none is domain truth. Existing `docs/` files are
raw material to fold in, not authorities.

> **Architecture rule (from the `BACKTEST_ENGINE` review):** an Architecture doc is a
> **language-independent contract** — SHALL/MUST clauses, no file/line references, no "the current
> code already…". Anything that cites code or reports today's state goes in a companion
> `*_STATUS` / `IMPLEMENTATION_STATUS` note that is *expected to age with the code*. The contract
> should read the same after a rewrite to another language; the status note gets rewritten with it.

| Doc | Question | Raw material in repo |
|-----|----------|----------------------|
| `DATA_MODEL.md` ☑ **done** | *The Memory* — how does the system remember? (one representation per concept, append-only reference graph, **bitemporal** `event_at`/`known_at`, as-of; contract only) | — (contract only) |
| `DATA_PIPELINE.md` ☑ **done** | *Filling the Memory* — how does the world become Facts/Assessments? (the door where `known_at` is born; ingestion≠interpretation; contract only) | — (contract only) |
| `AGENT_ARCHITECTURE.md` ☑ **done** | *Who May Act* — agents = **role-bound producers** (Gatherer/Assessor/Decider); a decider may not feed itself; `agent`=automated, human=`actor`; contract only | — (contract only) |
| `BACKTEST_ENGINE.md` ☑ **done** | How is the Loop replayed? (Replay = Loop + Historical Clock; SHALL/MUST contract, **implementation-independent**) | — (contract only) |
| `IMPLEMENTATION_STATUS.md` ☑ **done** | Where does today's Python stand vs the architecture contracts (`BACKTEST_ENGINE`, `DATA_MODEL`, …)? (ages with the code) | `quant/backtest.py`, `quant/evaluate.py`, `quant/observations.py` |
| `REVIEW_SYSTEM.md` ☑ **done** | *Reading the Memory* — a review = a read-only `(window, vantage)` view; **arrange, never judge**; dashboard = live review; contract only | — (contract only) |
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
- ☑ `00-VISION.md` — problem · goals · non-goals · long-term vision
- ☑ `01-PHILOSOPHY.md` — 5 principles on an SDA/language foundation: P1 observation≠interpretation · P2 past-observable · P3 time-not-cheated · P4 authority-earned · P5 language-outlives-implementation

**Domain (White Paper)**
- ☑ `10-ONTOLOGY.md` — frozen 7 concepts (`spec/ontology.md`)
- ☑ `11-DECISION_LOOP.md` — flow + forbidden edges (firewall, append-only, single feedback edge)
- ☑ `12-DECISION_INTELLIGENCE.md` — knowledge + strategy + learning (§C Evaluation split out → `14`)
- ☑ `14-EVALUATION_MODEL.md` — dimensions + matched/per-actor Outcomes + authority ladder (rungs here, numbers in arch)

**Architecture (evolving)** — begin only after `11`
- ☑ `BACKTEST_ENGINE` — Replay = Loop + Historical Clock; SHALL/MUST contract, implementation-independent
- ☑ `DATA_MODEL` — *The Memory*: one representation per concept, append-only reference graph, **bitemporal** (`event_at`/`known_at`), as-of reconstructable; "time protected by topology, not convention"
- ☑ `DATA_PIPELINE` — *Filling the Memory*: the door where `known_at` is born; ingestion (world→Fact, live-only, once) ≠ interpretation (Fact→Assessment, repeatable, any clock)
- ☑ `AGENT_ARCHITECTURE` — *Who May Act*: agents = role-bound producers (Gatherer/Assessor/Decider); decider may not feed itself; agents earn, never granted
- ☑ `REVIEW_SYSTEM` — *Reading the Memory*: read-only `(window, vantage)` view; **arrange, never judge**; dashboard = live review
- ☑ `IMPLEMENTATION_STATUS` — current Python vs the contracts (code refs + limitations; ages with the code)
- ☐ `API` · ☐ `DEPLOYMENT`
- ☐ reconcile existing `docs/ARCHITECTURE.md` + `docs/STRATEGY_ENGINE.md` into the above

**Project**
- ☑ `99-ROADMAP.md` → `architecture/99-ROADMAP.md` — living execution plan, *From Assistant to Earned Autonomy*; foundations (`known_at` axis = P0, record separation + decider-isolation = P1) gate everything; autonomy = P5, conditional

**Invariants to check on every doc**
- ☐ answers exactly one question
- ☐ uses only the 7 Ontology words (a new noun → Concept Test first)
- ☐ references the Ontology, never redefines it
- ☐ nothing earlier in Language→Behavior→Implementation depends on something later
