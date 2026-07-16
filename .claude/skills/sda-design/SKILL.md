---
name: sda-design
description: Apply Seed-Driven Abstraction (SDA) to design a domain/model before its implementation — plant the smallest stable concept, grow it only when reality demands, and prune to the essential. Use when the user asks to design a domain / data model / DSL / schema / API, asks "how should I model X", "name these concepts", "should these be one concept or two", "review my abstraction / architecture", or is about to stand up a new subsystem — even if they don't say "skill".
---

# Seed-Driven Abstraction

> **Reality grows the model. Designers do not.**

Design the *language* before the system. Find the domain's truths, plant the smallest stable
concept, and let the model grow from observed reality — not from a blueprint drawn up front.
Whenever a design task starts with structures, classes, tables, or code, **stop and go back to the
domain first**.

## The method

Run these in order on any design task. Do not skip to implementation.

1. **Describe What, not How** — name the domain's truths and *responsibilities* before any
   structure. Keep semantics separate from execution: the specification says what is true; the
   runtime is just one way to make it so.
2. **Plant the seed** — start from the single smallest *stable* concept the domain can't do
   without. Name it deliberately — the name shapes how everyone thinks. One concept, one
   responsibility.
3. **Grow only when reality demands** — add a concept *only* when the current model cannot explain
   an observed case, and *only* if the new concept introduces a genuinely **new capability**. If it
   adds no capability, it doesn't earn its place.
4. **Keep specification above runtime** — the spec must outlive any framework, storage engine, or
   language. Assume every runtime is replaceable; don't let the model depend on one.
5. **Prune** — remove until nothing essential can be removed. Simplicity is *discovered* by
   deletion, not designed in advance. The best abstraction explains the most with the fewest
   concepts.

## Smell tests

Apply these to every proposed concept set — they decide merge / split / remove:

- Two concepts that **always change together** → probably **one**. Merge them.
- One concept serving **multiple purposes** → probably **two**. Split it.
- A concept that introduces **no new capability** → **remove** it.
- A "concept" that only *describes* a case but doesn't *explain* it → not an abstraction yet. Wait
  for the pattern to repeat before naming it; don't abstract from a single instance or inspiration.
- Optimize for **evolution, not completion**. A wrong concept costs far more than wrong code — code
  is rewritten, a bad concept infects everything built on it.

## Review checklist

For an existing model/architecture, grade each **OK / Caution / Problem** with a one-line fix:

1. **Seed stability** — is the core concept genuinely stable, or does it shift when requirements do?
2. **One responsibility per concept** — any concept doing two jobs? (apply the split test)
3. **What/How separation** — is the model tangled with its implementation or a specific runtime?
4. **Spec vs runtime** — would the spec survive swapping the framework/DB/language wholesale?
5. **Over-abstraction** — any concept present that adds no capability? (apply the remove test)
6. **Missing merge/split** — run the smell tests across the whole set.
7. **Minimality** — can anything be deleted with nothing essential lost?

## The Zen (backing principles)

The method above is derived from these. Cite them when justifying a call.

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

## Output

Chat only — no file writes/edits unless asked. Lead with the **seed** and the current **concept
set** (each with its one responsibility). Then apply the smell tests, naming every merge / split /
remove with its reason. End with the single most important simplification. Keep the domain visible
and the framework invisible — the reader should see the model, not the machinery.
