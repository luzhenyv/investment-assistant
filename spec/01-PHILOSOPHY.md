# Philosophy — Why It Is Designed This Way v1.0

> **The question this document answers:** *why is the system designed the way it is?* — the principles beneath the choices.
> 
>It states **principles, not concept definitions** (those are in `10-ONTOLOGY`). The domain docs *implement* these principles; here we say only why they are worth implementing, and where a principle has a mechanism we **point** to it rather than restate it.

---

## The foundation — language, grown from reality

Everything in `spec/` rests on one idea from Seed-Driven Abstraction (`.claude/skills/sda-design`):

> **Names shape thinking, so the language *is* the architecture.**

Get the words right and correct solutions become natural; get them wrong and no amount of code recovers. And the language is not designed up front — it is grown:

> **Reality grows the model. Designers do not.**

So we start from the smallest stable concept, add one only when reality demands it, discover simplicity by *deletion*, and optimize for the model's capacity to **evolve**, not for a finished feature set. This is why there are only **7 concepts**, why we keep pruning, and why a new noun is a *request to grow the model*, not a free addition.

The five principles below are what that language commits us to.

---

## The principles

### P1 · Separate observation from interpretation
What is **observed** is kept apart from what is **made of it** — in this model, a *Fact* (what happened) apart from an *Assessment* (what we judge it to mean). This is the deepest split in the whole system. Interpretation is fallible and *should* improve; what was observed must never be corrupted when it does — so a better rule tomorrow never rewrites the record of yesterday. And because every judgment stays traceable to what was observed, every decision can be explained: **explainability is a property of the model, not a report.**

### P2 · The past must remain observable
You can only learn from a past you did not quietly revise — and retrospection and backtest are the *same read* only when nothing was ever changed. *(Mechanism: the Loop is append-only — records are added, never edited.)*

### P3 · Time must not be cheated
A decision may be judged **only by what was knowable when it was made.** This is not a technical convenience to prevent a bug — it is an **epistemic commitment against self-deception.** A system that lets tomorrow's information leak into yesterday's choice is lying to itself, and its every measurement becomes worthless. *(Mechanism: the temporal firewall.)*

### P4 · Authority must be earned
**Authority is earned through measured performance, and responsibility always accompanies authority.** Measurement precedes trust; trust precedes authority; and whoever — or whatever — holds the authority to decide holds the accountability for it. This is why the system *measures* and never crowns itself: to grant yourself authority is to skip the earning. Today no machine has earned that record, so the human decides and the system proposes — not as a permanent law, but as the current state of an earned progression.

### P5 · Language outlives implementation
The **specification** — vocabulary and behavior — must survive any change of framework, database, agent design, or language. Implementations are replaceable; the language is the durable asset. This is the direct consequence of the foundation above, and why the docs are frozen in two layers: a stable `spec/` and an evolving `architecture/`.

---

## What we refuse

Four lines, each the shadow of a principle. The system will never:

- **rewrite the past** — *(P2)*
- **cheat time** — *(P3)*
- **hide its reasoning** — *(P1)*
- **let the code define the model** — *(P5)*

---

## The creed

> **Reality grows the model. History is never rewritten. Time is never cheated. Authority is earned, never assumed.**

Everything else in this specification is a consequence of those four lines.
