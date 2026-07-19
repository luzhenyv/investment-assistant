# Agent Architecture — Who May Act v1.0

> **Layer: Architecture.** A language-independent contract. It introduces **no concept** — the Ontology
> already ruled that agents are *runtime* (`10`). It composes `11-DECISION_LOOP` (firewall,
> append-only), `DATA_PIPELINE` (`known_at`, ingestion ≠ interpretation), `DATA_MODEL` (attribution),
> and `14-EVALUATION_MODEL` (the authority ladder) — reusing their vocabulary, restating none. It names
> no model, framework, or tool. The state of today's agents lives in `IMPLEMENTATION_STATUS.md`.
>
> **Question this document answers:** *what may act inside the Loop — and what must anything that acts
> obey?*

---

## Responsibility

An Agent Architecture has **one** responsibility:

> **To let any automated producer take part in the Loop — while guaranteeing that nothing it produces
> can escape the constraints the Loop already places on Facts, Assessments, and Decisions.**

Agents add **capability**. They never add **authority**, and they never earn **exemption**.

---

## An agent is a role, not a thing

"Agent" is not an entity to be modeled. It is **whatever plays a role**, and a role is defined by the
record it produces:

| Role | Produces | Bound by |
|------|----------|----------|
| **Gatherer** | Facts | `DATA_PIPELINE` — stamps `known_at`, cannot ingest the past, append-only |
| **Assessor** | Assessments | reads Facts only through the as-of gateway; stamped with itself + version |
| **Decider** | Decisions (the engine `actor`) | justifies only with Assessments; authority bounded by `14` |

Any rule, model, ensemble, or automated process may be an agent **if it obeys the role's contract** —
the architecture fixes the roles, not the agents. A **human** is an `actor` (Ontology `Decision.actor`
= human | engine), **not an agent**: "agent" means an *automated* actor or producer. Keeping the human
outside the word is what keeps it first-class.

---

## The one separation that matters — a decider may not feed itself

A deciding agent **MUST NOT** produce the Assessments it consumes.

An agent may gather and assess freely for other ends, but the evidence a **Decision** rests on must
come from an assessor the decider **did not author.** Otherwise a single agent writes both the verdict
and the reasons for it, and the explainability chain `Decision → Assessment → Fact` collapses into one
author justifying itself. **Evidence and choice must be held in different hands** — that is the
difference between a reasoned decision and a rationalization.

---

## Every output is attributed

Every record an agent produces **SHALL** carry the agent's **identity and version** (`DATA_MODEL`
provenance; `01` P5). *"Which agent, at which version, produced this?"* is always answerable. Without
it, an agent's output cannot be measured, compared, or replaced — and an unmeasurable producer can
never earn anything.

---

## Agents are plural and replaceable

Many agents may play the **same** role. Several assessors may read the same Facts and produce separate
Assessments that **disagree** (`11`) — that is normal, not an error. An output is weighted by its
earned **reliability** (`12`, `14`), never privileged for being an agent's. And because the *contract*
is fixed, not the agent, any agent is replaceable: swap it and the Loop is unchanged.

---

## Agents obey the firewall

An agent producing a judgment reads only through the **as-of gateway** — never the future (`11`,
`DATA_MODEL`). A gatherer reaching the live world stamps `known_at =` now and cannot inject knowledge
into the past. **Being "an AI" grants no special access** — not to data it should not see, and not to
time it cannot have known.

---

## Agents earn; they are not granted

This is where the ambition of autonomy meets its bound:

- an **assessor** earns *reliability*, per perspective — a new assessor starts unweighted and earns
  influence only by being right (`12`, `14`);
- a **decider** earns *authority*, per `14`'s ladder — it starts at **report** / **shadow**, cannot
  promote itself, and cannot climb at all on a record built from non-point-in-time data
  (`BACKTEST_ENGINE`).

An agent may become more capable overnight. It may become more *trusted* only over an honest measured
record. Capability is added; **authority is earned, never assumed** (`01` P4).

---

## What an agent MUST NOT do

- produce a record **without its identity and version**;
- as a **decider**, consume Assessments **it authored** (self-justification);
- read **outside the as-of gateway** — no private path to data, no reach into the future;
- claim **authority it has not earned** on an honest record;
- write a **record type outside the role** it is playing (an assessor writing a Decision);
- **edit or delete** any record — append-only holds for agents too.

---

## Out of scope

*Which* agents exist (a screener, a researcher, an ensemble of assessors), how they are orchestrated,
and their prompts, models, tools, and frameworks — and *what today's code provides* — belong to
`IMPLEMENTATION_STATUS.md` and lower design. This contract holds whatever the agents are.

> **An agent may see, may judge, may propose. It may never crown itself.**
