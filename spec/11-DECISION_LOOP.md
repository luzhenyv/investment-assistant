# The Decision Loop — Behavior v1.0

> **Question this document answers:** *how do the 7 concepts flow?* — who may read whom, and which edges are forbidden.
> 
>It introduces **no new concepts**. Every noun here is defined in `10-ONTOLOGY` (`spec/ontology.md`). The Ontology says *what exists*; this document says *how it moves*.
> 
> **The Decision Loop is an information flow, not an execution workflow.** A workflow stresses *executing steps*; the Loop stresses how *information is progressively compressed into an action, then re-expanded into knowledge*. That is the shape of any decision system — not just investing.

---

## An information flow, not a workflow

Read as pure decision theory, the 7 concepts are the seven stages every decision passes through:

| The 7 concepts | Read as decision theory |
|----------------|-------------------------|
| Fact | Information |
| Assessment | Knowledge |
| Strategy | Policy |
| Decision | Choice |
| Execution | Reality (the act meets the world) |
| Outcome | Evidence |
| Evaluation | Measurement |

The **front half** (`Fact → … → Decision`) *compresses* a flood of information into a single act. The **back half** (`Execution → … → Evaluation`) *expands* that act back into knowledge, which re-enters the next pass. Compression, then expansion — that is the loop.

---

## The loop

```
   time →      ‹───────  ≤ t : knowable  ───────›   t : act      ‹──  ≥ t+h : realized  ──›

   Fact ──▶ Assessment ──▶ Strategy ──▶ Decision ──▶ Execution ──▶ Outcome ──▶ Evaluation
                 ▲                                                                   ┆
                 └┈┈┈┈┈┈┈┈ next pass only ┈┈ perspective reliability + Strategy(vN+1) ┘
```

Read left→right as one pass. The dashed edge is the **only** feedback, and it lands on the **next** pass — never on the records this pass produced. The loop does not travel back in time.

---

## Time is the backbone

Every pass has a **decision instant `t`** and a **horizon `h`**. Three eras divide it:

| Era | Contains | Rule |
|-----|----------|------|
| **≤ t — knowable** | Facts and Assessments with time ≤ t | everything judgment is allowed to see |
| **t — the act** | Strategy → Decision → (Execution begins) | the choice is made using only the knowable era |
| **≥ t+h — realized** | future Facts, Outcome, Evaluation | exists only *after* the act; may never inform it |

The firewall is simply: **judgment made at `t` may read only the ≤ t era.** Look-ahead bias is not "discouraged" — a Strategy has no edge to anything in the realized era, so it cannot be written.

---

## Each concept's place in the flow

| Concept | May read (time-bounded) | May **never** |
|---------|-------------------------|----------------|
| **Fact** | — (a source; ingested) | — |
| **Assessment** | Facts with time ≤ its own timestamp | any Fact *after* its timestamp |
| **Strategy** | Assessments ≤ t (its evidence); *operational* Facts ≤ t (cash, holdings, market-open) as context | Outcomes; any Fact > t; **justify with raw Facts** |
| **Decision** | the Assessments, the engine's Decision, Facts ≤ t | future Facts; Outcomes |
| **Execution** | — it does not read; it *is* the market's response to an accepted Decision | — |
| **Outcome** | Facts with time > t, over the horizon | write back into the Decision; exist before t+h |
| **Evaluation** | Outcomes, the Decision/Strategy, Criteria | mutate any record; *judge* (it **measures**) |

Consequences worth stating plainly:

- **Assessments may disagree.** *Value* may say buy while *Trend* says sell. The Loop does **not** force consensus — reconciling conflicting Assessments is the Strategy's job, and disagreement across assessors is normal, not an error.
- **Strategy justifies only with Assessments.** It may read *operational* Facts (cash, holdings, market-open) as **execution context**, but a Decision's *justification* must trace to Assessments, never to raw Facts — otherwise the Strategy is silently re-doing the assessor's interpretation.
- **Execution is an interaction, not a read.** It is the market's *response* to an accepted Decision (`Decision → broker → fills`), not a reading of market state.
- **Outcome reads forward but never writes back — and does not exist until its horizon ends.** The daily marks along the way are *Facts*; the Outcome is computed **once, at t+h, then frozen**.

---

## Shape of the flow

Two multiplicities are *behavioral* (not storage — how they are indexed is Architecture's concern):

- A **Strategy may propose nothing.** No-action is a valid pass, not a failure.
- One accepted **Decision may produce several Executions** (partial fills over time).

(A single Fact may also feed many Assessments, and one Assessment may rest on many Facts across time — but that is a reading of the flow, not an entity-relationship diagram.)

---

## The invariants (the loop's hard rules)

1. **Append-only (event-sourced).** No record is ever mutated; the system only *appends*. Every record — Fact, Assessment, engine/human Decision, Execution, Outcome, Evaluation — is an immutable event. *Event-sourcing is a property of the flow, not an eighth concept — the nouns stay the 7.*
2. **Temporal firewall.** Any judgment produced at `t` (Assessment, Strategy, Decision) may read only records with time ≤ t. Outcomes and future Facts are structurally unreachable from it.
3. **Single feedback edge.** The only thing that flows backward is Evaluation → *future* passes: it re-weights **perspective reliability** (used by later Assessments) and informs the next **Strategy version**. It never alters the pass it evaluated.
4. **No skipping; justify only with Assessments.** The judgment path is `Fact → Assessment → Strategy → Decision`. An Execution may arise only from an *accepted* Decision; an Outcome may bind only to an existing Decision; a Decision may be justified only by Assessments.
5. **Evaluation measures, it does not judge.** It emits numbers (ROI, Sharpe, precision, drawdown) under stated Criteria. The *judgment* — is this good enough? — belongs to the human.
6. **An Outcome freezes once.** It does not exist until its horizon ends; then it is computed a single time and never revised. Interim marks are Facts, not Outcomes.

---

## Decision lifecycle — append-only events

Because the Loop is event-sourced, a Decision's "status change" is **not** an in-place edit. Engine Decision, human Decision, and Execution are all **append-only events**, each linked to the one it answers:

```
Decision{actor: engine, status: proposed,  action: buy, ...}          ← the engine's choice
        └─▶ Decision{actor: human, status: accepted | rejected | ignored, responds_to: ↑}   ← the human's choice
                    └─▶ Execution{...}          ← exists only if accepted and the market responds
```

- The engine's record is born `proposed`; the human's is born `accepted` / `rejected` / `ignored`. Both persist forever — this is what lets Evaluation measure engine and human **independently**, and it makes audit, replay, and backtest one and the same read.
- **`executed` is derived, not written.** A Decision is "executed" precisely when a linked Execution exists; the Loop never reaches back to stamp the Decision.
- An `ignored` human Decision is a *recorded* choice, not an absence — no-action is first-class.

---

## First-domain trace — one equity situation through the loop

`t = 2026-07-18`, horizon `h = 30d`. NVDA, a `core`-sleeve name.

| When | Record |
|------|--------|
| ≤ t | **Facts**: price, volume, MA/RSI, forward-EPS estimate (each an ingested Fact ≤ t) |
| ≤ t | **Assessments**: `{perspective: Value, result: fair, conf: 0.7}`, `{perspective: Trend, result: improving, conf: 0.6}` — may disagree |
| t | **Strategy(v3)** reads those Assessments (+ cash/holdings as operational context) → proposes |
| t | **Decision**{actor: engine, status: proposed, action: add, sleeve: core} |
| t | **Decision**{actor: human, status: accepted, responds_to: ↑} |
| t+ | **Execution**{filled 40% of intended tranche} → Decision is now *derived-executed* |
| **t+30d** | **Outcome**{horizon: 30d, realized: +12%, path: …} — frozen only now, at horizon end |
| t+30d | **Evaluation**{ROI: +12%, engine precision on this setup, human adopted?} |
| next pass | feedback: Value-perspective reliability ↑; Strategy v3→v4 candidate |

The 30-day gap between the act and its Outcome is *why* the firewall matters — and why Evaluation can never be an input to the Decision it grades.

---

## Out of scope — but one thing implementation may not touch

*Where* records live, *how* the assessor runs, *how* the market is reached, *how* Outcomes are computed on a schedule — all belong to `architecture/` (`DATA_MODEL`, `DATA_PIPELINE`, `AGENT_ARCHITECTURE`, `BACKTEST_ENGINE`).

**Any implementation may change — agents, pipeline, API, storage, language — but it must preserve the Loop:**

```
Fact → Assessment → Strategy → Decision → Execution → Outcome → Evaluation
```

…and every forbidden edge above. The Loop is the contract; everything else is negotiable.
