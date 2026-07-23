# Investment Assistant — Refactor Execution Plan

> Status: execution specification for the **current stage**, derived from the recorded design discussion.
>
> Companion to [REFACTOR_PLAN.md](REFACTOR_PLAN.md) (the constitution / standard). This document is the
> execution layer; the two coexist and cross-reference. **Where they conflict, this document governs
> for the current stage** (it records decisions taken after the constitution was written).
>
> Current-stage scope: **(1) data archival, (2) engine refactor, (3) lens lifecycle.**
> Deferred to a later stage: engine/agent/human interaction and the domain model — REFACTOR_PLAN.md
> §3 (Thesis/View/Plan/Sleeve/Overlay/Episode), §4 (authority), §3.6 (Decision Episode), the full
> five-record event model in §5, and Phases 4–7 of §14.
>
> Time convention: every wall-clock timestamp is UTC (`quant/clock.py`); exchange sessions are market
> calendar dates.

---

## 1. Relationship to REFACTOR_PLAN.md

- **Confirms:** §2 (constitution), §5 (point-in-time), §7 (freshness), §8 (lens lifecycle), §10
  (workflow direction). Nothing here weakens them.
- **Resolves** several §13 open decisions (see §2 below): engine may absorb lenses (B-path), the only
  implemented influence verb is `gate`, the weekly review becomes a pure view, the report is
  co-located inside the session directory, and multi-timeframe is a captured feature axis (1d/1w).
- **Simplifies / defers:** the §3 domain model and §4 authority split are *not* built this stage. The
  current spine is three objects only: **the session capsule, the lens contract, and the gate waist.**
- **Distinguishes two layouts REFACTOR_PLAN.md §14 Phase 8 / §17 keep deferred:** that deferral is
  about the **code package** layout. This stage fixes only the **data archive** layout (the capsule
  tree, §4 here) — which *is* the archival work prioritized now. The Python package/module layout
  stays deferred until workflow boundaries stabilize.
- **Re-anchors acceptance:** every exit criterion rolls up to one test — *reconstruct a wrong
  prediction from three months ago using only the context available at that time* (§10 here, §16 there).

## 2. Locked decisions (authoritative for the current stage)

Each entry names the REFACTOR_PLAN.md section it refines or resolves.

1. **Atomic unit = the session slice** (capsule), addressed by `(profile, session_date, symbol)`;
   `session_date = bar_date`, never the run wall-clock. *Concretizes §2.2, §5.1, §10.1.*
2. **Report = a pure view of the capsule**; capture and rendering are separate steps. A report must be
   reconstructible from stored evidence with no engine run and no live fetch. *Concretizes §2.2, §10.*
3. **Archival rule:** anything re-derivable from a global source does **not** enter the capsule (price
   bars → `data/cache/`, global); anything lost forever if not captured **does** (headlines, sentiment,
   chains, prediction odds, and the day's decision label). *Concretizes §2.2, §2.3.*
4. **Lens lifecycle `off → report → shadow → live`** maps to §8 as: `report` = Context (§8.1),
   `shadow` = Shadow (§8.2), `live` = promoted / Engine-eligible-and-active (§8.3); `off` = disabled.
   Moving a lens `report → shadow` is the explicit act that starts its graduation clock. *Refines §8.*
5. **Decision influence verb = `gate` only** (a post-filter that can block/downgrade a base intent).
   `size` and `rank` are **reserved interface words**, documented but not implemented (§9 here). This
   is about *which mechanism exists in code*, not about lowering the promotion bar — §8's higher
   standard for a hard gate still governs whether any lens may go `live`. *Refines §8, §2.7.*
6. **Engine may absorb graduated lenses (B-path)**, but the default engine is OHLCV-only and stays
   pure; lens signals enter only through the narrow gate waist, config-gated per lens. With every lens
   at `report`, production behaviour is byte-identical to today. *Resolves the composability question
   left implicit in §2.7 / §13.5; honours §17 — no current lens is promoted this stage.*
7. **Honesty rule:** once a non-backfillable lens goes `live`, the backtest cannot reproduce it. The
   backtest therefore validates only the **backfillable core** and never contains a non-backfillable
   lens. *Refines §11.2.*
8. **Multi-timeframe = a captured feature axis, not a cadence.** Two frames only (1d/1w), a curated
   subset of surviving indicators, wide suffixed columns (`rsi_1w`), grain unchanged. As-of safety: the
   already-sliced daily frame is resampled, so the current week is a forming (partial) candle — exactly
   what a trader sees. *New refinement; distinct from §2.5, which is about thesis horizons.*
9. **Workflow = one heartbeat, several views, one live exception.** Daily capture is the only writer of
   capsules (with a freshness hard-gate); weekly/daily reports are views; `pretrade` is the only tool
   that reads live and is never stored as a capsule. *Refines §10.1, §10.3, §10.4.*
10. **`schema_version` co-versions the indicator set and the panel columns**; the schema changes only
    at cutover. Indicator pruning is **low priority** this stage (duplicate indicators do not affect
    operation) and, if done, happens inside the cutover migration. *Refines §2.6, §6.3.*

## 3. Core vs Extension

| | Belongs to | Property |
|---|---|---|
| **Core** (spine, maintained rigorously) | capsule store + schema/version + `load_capsule` + the lens contract + the decision engine + the gate waist + the evaluator | correctness and point-in-time discipline live here |
| **Extension** (leaves, cheap to add/remove) | an individual lens, a report view, an agent skill, the MTF indicator selection | adding or removing one must not touch the spine |

## 4. Data archival — the capsule contract

Today the non-backfillable evidence is scattered across five trees (`daily_observations/`,
`options_snapshots/`, `sentiment_snapshots/`, `news_snapshots/`, `prediction_markets/`). The target
collapses **one session into one directory**:

```
data/
  cache/                                    # price parquet — global, backfillable, NOT in the capsule
  sessions/<profile>/<session_date>/
      panel.parquet    config.json          # wide panel (incl. _1w columns) + resolved config snapshot
      news.json  sentiment.json  chains.parquet  prediction_markets.json
      report.md                             # rendered view, co-located with its evidence
  eval/<profile>/                           # cross-session graded outcomes
```

- `load_capsule(profile, date) → CapsuleView` is the **sole** data entry point for post-mortem skills,
  so a reconstruction physically cannot reach future information (serves §10 here / §16 there).
- Session-level envelope (this stage): `market_session` (= `session_date`), `recorded_at` (UTC
  `create_time`), provenance (`git_sha`, `config_hash`, `config.json`), and per-lens freshness
  (`fresh|stale|missing|error`, §7 there). The full per-evidence `available_at` and the five-record
  event model (§5 there) are **next stage**.
- Freshness hard-gate: a partial / mid-session bar must **not** be written as a canonical capsule
  (maps to §7.2 `failed`). This replaces today's soft warning.

## 5. Engine + lens — contract and lifecycle

**Lens contract.** A lens is one module declaring: `name`, `backfillable: bool`, `fetch(cfg)`,
`analyze(raw, ctx) → LensView`, `columns() → schema fragment`, `render(view) → md block`, and an
optional `gate(view) → GateEffect`. Lenses are discovered from a **registry**; `pipeline.run`'s
repeated per-lens loops collapse to one registry iteration gated by `(state, breadth)`. Adding a lens
becomes *one file + one registry line* (delivers §14 Phase 2 / Phase 8 exit: no central context object
grows per lens).

**Lifecycle (config-driven per lens):**

- `off` — not fetched.
- `report` — fetched, analysed, rendered, panel observation columns written; never touches the
  decision. (All seven lenses start here.)
- `shadow` — additionally computes and **records** its `gate` effect (would it have blocked?), but does
  **not** apply it. This is where graduation evidence accrues; the grader itself is deferred.
- `live` — computes, records, and **applies** the gate.

**Gate waist.** `decide_holding` stays pure; a wrapper `apply_gates(base_intent, live_gates) →
final_intent` sits after it. The panel records `base_intent`, `applied_gates`, and `final_intent`, so
every decision is attributable. With no non-backfillable lens `live`, the wrapper is the identity and
the backtest core is unchanged.

## 6. Workflow / SOP

| Role | Who | Definition |
|---|---|---|
| Heartbeat (only writer) | daily capture | post-close; writes the session capsule; freshness hard-gate. The only place non-backfillable evidence is created. |
| Views (readers) | weekly / daily reports | pure functions of the capsule. Weekly stops running a second engine and becomes a strategic view over recent sessions emphasising `_1w` features + period deltas — removing the `cadence="weekly"` double-write and the `__weekly` suffix hack. |
| Live overlay (only exception) | `pretrade` | the only tool that legitimately reads live intraday data; never writes a capsule (a mid-session bar is gated out anyway). |
| Cross-session reader | `evaluate` | grades stored labels — and later, recorded shadow gates — against forward returns. |
| Backfillable-core replay | `backtest` | validates only the backfillable core; never contains a non-backfillable lens (§2.7 here). |

## 7. Phased execution

All work happens in a git worktree. During the refactor, capsule data written in the worktree is
throwaway test data (a worktree has its own empty `data/`); the real non-backfillable history stays in
the main checkout and the current daily scripts keep running there until cutover. Each phase has an
observable exit criterion; a later phase must not start merely because earlier code was rearranged.

**Phase A — Freeze & protect** *(data archival)*
Add `schema_version` to the current panel writer (identity change). Inventory every non-backfillable
artifact on disk so cutover can fold it in with zero loss.
*Exit:* the inventory lists the non-backfillable files for every existing session; main-checkout
daily/weekly/pretrade still run unchanged; `pytest` green in the worktree.

**Phase B — Capsule store + capture/render split** *(data archival + engine refactor)*
Implement the session writer (capsule tree, freshness hard-gate) and `load_capsule`. Split daily into
`capture` (writes the capsule) and `render` (reads it → `report.md`).
*Exit:* one `capture` run yields a self-contained session directory; discarding the in-memory engine
and running `render` from the directory alone reproduces `report.md`; the gate refuses a mid-session bar.

**Phase C — Lens contract + registry** *(engine refactor + lens lifecycle)*
Define the lens protocol; register the seven lenses; collapse the repeated pipeline loops into registry
iteration; panel columns come from `lens.columns()`; add a per-lens lifecycle state in config (all start
`report`); add the optional `gate()` (unused until a lens reaches `shadow`).
*Exit:* a trivial eighth lens is added with one file + one registry line and no edits to the
pipeline/report/schema writer beyond registration; removing it leaves no orphan; the seven existing
lenses produce byte-identical panel columns vs today (golden test).

**Phase D — MTF feature axis (1d/1w)** *(engine refactor)*
Resample the sliced daily frame to weekly; compute the curated survivors at 1w; store `_1w` columns
(grain unchanged). Weekly becomes a pure view; delete the weekly double-write and `__weekly` hack.
*Exit:* the weekly view renders from a daily capsule with no second engine run; a known symbol's `rsi_1w`
matches an independent weekly resample; backtest produces the `_1w` columns as-of with the current week
partial and zero look-ahead.

**Phase E — Gate waist + shadow logging** *(engine refactor + lens lifecycle)*
Wrap `decide_holding` with `apply_gates`; record `base/applied/final` intents. `shadow` lenses record
their would-be gate without applying it; `live` lenses apply it. No lens is promoted this stage.
*Exit:* with all lenses at `report`, `final_intent == base_intent` for every row (engine still pure
OHLCV); flipping one backfillable lens (e.g. sectors) to `shadow` records its would-be gate and leaves
decisions unchanged; backtest output is identical to pre-Phase-E (proves core purity).

**Phase F — Cutover (zero session loss)** *(data archival)*
A one-time migration folds all main-checkout non-backfillable history (sessions ≤ D) into
`data/sessions/` under the new schema (dropping duplicate/dead columns here is optional and
low-priority). Old daily runs stop at D; new capture runs from D+1. Old entry points become views or
retire.
*Exit (= global acceptance, §10 here):* pick a session ≥ 3 months old from the migrated store;
`load_capsule` reconstructs the panel row plus that day's exact headlines / chain / sentiment / config;
`render` reproduces its `report.md`; a post-mortem skill can explain a wrong intent using only capsule
data. **No session is missing between the first-ever capture and D.**

## 8. Reserved and deferred

- **Reserved interface words** (the full decision-influence vocabulary — documented so future work
  extends the same waist rather than inventing new mechanisms):
  - `gate` — implemented: block / downgrade an intent (boolean).
  - `size` — reserved: scale a staged `dollar_gap` (e.g. ×0.5–1.5).
  - `rank` — reserved: reorder / weight watchlist candidates.
- **Deferred to a later stage:** the shadow grader (graduation significance test), the §3 domain model
  (Thesis/View/Plan/Sleeve/Overlay/Episode) and §4 authority split, the engine/agent/human decision
  journal, the full five-record event model, indicator pruning, and a monthly timeframe.

## 9. Global acceptance

> Stand at a session three months in the past and reconstruct a wrong prediction using only the context
> available then: `load_capsule(old_date)` opens that session directory, yields everything captured that
> day, and physically cannot reach future data. Every other phase exit is a prerequisite of this test.
