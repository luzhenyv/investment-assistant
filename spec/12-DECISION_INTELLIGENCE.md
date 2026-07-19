# Decision Intelligence — How the System Improves v1.0

> **Question this document answers:** *how does the system become better at making future Decisions?*
>
> It introduces **no new concepts**. Knowledge, Strategy, and Learning are three **facets of this one question** — not three co-equal topics, and not new abstractions. The moving concepts underneath are the Ontology's **Assessment → Strategy → Evaluation** (`10-ONTOLOGY`); the flow rules are set in  `11-DECISION_LOOP`. This document only says how those improve.

---

## One question, three facets

A better future Decision comes from three things getting better:

- **What the system knows** — the Assessments a Decision can draw on. *(Knowledge)*
- **How it chooses** — the way Assessments become a Decision. *(Strategy)*
- **What actually improves** — and the answer is surprisingly small. *(Learning)*

"Knowledge", "Judgment", and "Learning" are **lenses**, not layers. The real chain is the Ontology's:

```
   Assessment ──▶ Strategy ──▶ (Decision … Outcome) ──▶ Evaluation
       ▲                                                    │
       └────────────── Learning updates ────────────────────┘
              reliability of Assessments  +  version of Strategies
```

---

## A · Knowledge — what the system knows

**Knowledge is not a store.** Knowledge is the **accumulated Assessments about a Subject.** That is the whole definition.

It is **append-only** — you never overwrite what you believed, you add to it — which is what lets the system reconstruct *what it knew about a Subject on any past date*. It does not contain track records, outcomes, or reliability; those are produced by Learning and merely *weight* the Assessments when a Strategy reads them.

*Domain-independent:* a Subject is a company (equity), a patient (medical), a market (macro). The shape does not change.

---

## B · Strategy — how the system chooses

**A Strategy maps Assessments → a Decision.** It is **versioned**. That is all the White Paper fixes.

Two constraints, inherited from `11-DECISION_LOOP`:

- **Justified only by Assessments** — never by raw Facts, never by anything after `t`.
- **Never sees the future** — no edge to Outcomes.

*How* the mapping is done — hand-written rules, an LLM, a learned model, a Bayesian net — is **left free** and belongs to `architecture/`. The White Paper constrains only the **shape** (Assessments in, Decision out) and the **honesty** (justified only by Assessments), never the method.

*First domain — every one of these is the same shape, `Assessments → Decision`:*

| Strategy (instance) | Reads (Assessments) | Proposes |
|---------------------|---------------------|----------|
| Left-side scaled entry | Value=fair/cheap, Trend=basing | staged `add`, sleeve=core |
| Right-side / momentum | Trend=strong, Structure=breakout | `add`, sleeve=trading |
| Mean-reversion | Value=fair, Trend=intact, stretched | `add` on pullback |
| Risk / diversification | Concentration=high | `trim` |

---

## C · Evaluation — how the system knows what worked

Evaluation **measures**; it does not judge (`11-DECISION_LOOP`). It binds Outcomes to a Decision/Strategy and computes **Criteria** — deliberately **dimensional**, never a single `hit`:

| Dimension | Measures |
|-----------|----------|
| **Return** | realized ROI; realized-vs-intended |
| **Risk** | drawdown, path volatility, risk-adjusted |
| **Decision quality** | precision / recall of proposals; hit-rate by setup |
| **Calibration** | did stated confidence match realized frequency? |
| **Explainability** | can the Decision be traced back to Assessments? |

**Per-actor and non-rivalrous.** Engine and human emit the *same* Decision concept, differing by `actor`, so they are measured **independently** over matched Outcomes. Two questions are one operation:

- *"Did Strategy v2 beat v1?"* — measure both over matched Outcomes.
- *"Is the engine better than me here?"* — measure both actors over matched Outcomes.

The system **measures**; the **human judges** whether the numbers are good enough. It never crowns a winner — autonomy is earned by an accumulating record, not declared by a scoreboard.

---

## D · Learning — what actually improves

Measurement and improvement are **two different actions**:

> **Evaluation measures. Learning updates.**

And when you ask *what* Learning may update, the answer is startlingly small. Everything the system produces is immutable history — Facts, Decisions, Executions, Outcomes — and the Loop and the Ontology themselves never change. So **exactly two things improve:**

```
                    ┌── the reliability of Assessments ──┐
   Learning updates │                                    │──▶ better future Decisions
                    └── the version of Strategies ───────┘
```

- **Reliability of Assessments** — a perspective that has been right earns more weight (optionally by context, e.g. a regime). This is how a signal *earns* influence instead of being granted it.
- **Version of Strategies** — Evaluation is the **Check**; a new Strategy version is the **Act**. PDCA, every step on the record.

Both land on the **next** pass, never the one that was evaluated. In one line:

> **The system learns only how much to trust its Assessments, and how to improve its Strategies.**

That sentence is the whole of Decision Intelligence.

---

## When to split this document

Keep Knowledge, Strategy, and Learning merged **until they need different lifecycles.** Length is not the trigger — *evolution rate* is. If Knowledge stays stable for a year while Strategy is revised monthly and Learning is tuned weekly, those different clocks are the reason to split into `12-KNOWLEDGE_MODEL` / `13-STRATEGY_FRAMEWORK` / `14-EVALUATION_MODEL`. Until their lifecycles diverge, one document is the more honest description.

---

## First-domain trace — what improved

NVDA, continuing the `11-DECISION_LOOP` example:

1. **Knows** — Assessments `{Value: fair, Trend: improving}`.
2. **Chooses** — Strategy(v3) maps them → a staged `add`.
3. **Measures** — 30 days on, Evaluation: ROI +12%, engine precision on this setup, Value well-calibrated.
4. **Improves** — Learning updates *exactly two things*: Value-perspective reliability ↑, and a Strategy v3→v4 candidate that leans harder on Value. The Facts, the Decision, the Outcome — all stay frozen forever.

---

## Out of scope

*How* Knowledge is stored, *how* a Strategy is coded, *how* Evaluation is scheduled — all belong to `architecture/`. This document constrains what those may do; it does not choose them. Any implementation may change, but: Knowledge stays append-only, a Strategy is justified only by Assessments, Evaluation stays dimensional and per-actor, and **only Assessment-reliability and Strategy-version ever improve.**
