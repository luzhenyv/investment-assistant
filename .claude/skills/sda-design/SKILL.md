---
name: sda-design
description: Apply Seed-Driven Abstraction (SDA) to design a domain/model before its implementation — plant the smallest stable concept, grow it only when reality demands, and prune to the essential. Use when the user asks to design or review a domain model / data model / DSL / schema / API / ontology / taxonomy / knowledge graph, asks "how should I model X", "name this concept", "should these be one concept or two", "what's the right aggregate / bounded context / entity", or works on domain language, classification, relationships, or a concept's responsibility — even if they don't say "skill".
---

# Seed-Driven Abstraction

> **Reality grows the model. Designers do not.**

> **Discover concepts. Never predict them.** Never invent a concept for an imagined future requirement. Add one only after repeated observation shows the current model can no longer explain reality. Reject "let's make it extensible / future-proof / support X one day."

If a design task opens with structures, tables, or classes, **stop and return to the domain first**. This skill has three layers — run **Execution**, decide with **Decision Rules**, justify from **Principles**. Only the Execution Procedure is meant to be *performed*; the rest is there to decide and to justify, not to recite.

## Execution Procedure

1. **Describe What, not How** — state the domain's truths and *responsibilities* before any structure. Keep semantics separate from execution: the spec says what is true; a runtime is only one way to make it so.
2. **Plant the seed** — the single smallest **stable** concept the domain can't do without. *Stable* = survives changing requirements, survives implementation changes, survives naming debates. Test: *"If requirements doubled tomorrow, is this concept still necessary?"* Beware generic nouns (Document, Record, Node, Item, Thing) — they feel stable but usually aren't.
3. **Run the Concept Test on every candidate concept** — see Decision Rules. This is the heart of the method: it decides existence, splits, and merges in one pass.
4. **Keep specification above runtime** — the spec must outlive any framework, storage engine, or language. Assume every runtime is replaceable; don't let the model depend on one.
5. **Prune** — remove until nothing essential can be removed. Simplicity is *discovered* by deletion, not designed up front.

## Decision Rules

**The Concept Test** — run top to bottom on each candidate concept:

```
├─ Explain an observed reality?      No → DELETE   (it describes nothing real yet)
├─ Introduce a new capability?       No → DELETE   (it adds no power the model lacked)
├─ Exactly one responsibility?       No → SPLIT    (it is secretly two concepts)
└─ Always changes with another?      Yes → MERGE   (they are secretly one concept)
```

**Discovery guard** — a concept justified *only* by an imagined future ("extensible", "future-proof", "we might need X") fails the first branch: it explains no observed reality. Delete it and wait for the pattern to actually repeat.

## Review mode

For an existing model/architecture, grade each **OK / Caution / Problem** with a one-line fix:

1. **Seed** — is the core concept genuinely stable (survives the "requirements doubled" test)?
2. **Responsibilities** — one job per concept?
3. **What vs How** — is the model tangled with its implementation?
4. **Runtime independence** — would the spec survive swapping the framework/DB/language wholesale?
5. **Concept health** — run the Concept Test on every concept; report each DELETE / SPLIT / MERGE.

## Output

Adapt to the task; don't force one shape onto every question.

- **Designing** → present the seed, then the concept set (each with its one responsibility).
- **Reviewing** → the 5 checks above with grades and fixes.
- **Naming** → justify the name from the seed and its single responsibility (names shape thinking).

Chat only — no file writes/edits unless asked. Keep the domain visible and the framework invisible.
**Always finish with the single biggest simplification available.**

## The Five Laws

1. Design the domain.
2. Plant the seed.
3. Grow only from reality.
4. Separate what from how.
5. Prune relentlessly.

## Reference — the full Zen

Cite these when justifying a call. Do not recite them unprompted.

1. Design the domain, not the implementation.
2. Seek truths that outlive technology.
3. Start with the smallest stable concept.
4. Add concepts only when reality demands them.
5. Every concept must introduce a new capability.
6. Responsibilities are more important than structures.
7. Describe **what** before deciding **how**.
8. Separate semantics from execution.
9. Specifications should outlive runtimes.
10. Treat every runtime as replaceable.
11. Let patterns emerge before creating standards.
12. Grow the model like a tree, not a blueprint.
13. Remove until nothing essential can be removed.
14. Simplicity is discovered, not designed.
15. The best abstractions explain more with less.

**Extended**

1. Names define thinking.
2. A concept should have one responsibility.
3. A model should explain, not merely describe.
4. Abstractions should emerge from repeated observations.
5. If two concepts always change together, they are probably one.
6. If one concept serves multiple purposes, it is probably two.
7. Optimize for evolution, not completion.
8. The cost of a concept lasts longer than the cost of code.
9. A good language makes correct solutions natural.
10. The best framework disappears behind the domain.

> **Reality grows the model. Designers do not.**
