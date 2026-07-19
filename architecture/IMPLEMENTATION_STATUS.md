# Architecture — Implementation Status v1.0

> **Layer: Architecture (status note).** This tracks where **today's Python implementation** stands
> against the architecture *contracts* (`BACKTEST_ENGINE`, `DATA_MODEL`, …). Unlike a contract, this
> doc **ages with the code** — the file/line references below *will* rot, and that is expected. When
> the code is rewritten, this doc is rewritten; the contracts are not. Nothing here is a
> specification; it is a snapshot.

Legend: ✅ satisfies the clause · ◐ partial · ☐ owed.

---

# Backtest Engine

## Against the `BACKTEST_ENGINE` contract

| Contract clause | State | Where / note |
|-----------------|-------|--------------|
| **Single Decision Path** — replay runs the live engine, not a copy | ✅ | replay calls `scoring.build_signal`, `market.detect_market`, `decision.decide_holding / rotation / scan_watchlist` (`quant/backtest.py:191-228`) |
| **As-of gateway** — all judgment reads ≤ t | ◐ | frames sliced to `date ≤ t` (`quant/backtest.py:60-61`, applied `:173,194,197`); indicators trailing-window over the slice (`quant/scoring.py:98-100`). Correct, but **bypassable** — not one enforced gateway |
| **Conformance test** — fails if any judgment reads > t | ☐ | none exists yet |
| **Next-instant execution** | ✅ | fills at next session open (`_open_as_of :69-72`, `t_exec = t+1 :232-240`); final bar dropped (`:233-234`) |
| **Path-aware Outcome** (terminal + MFE/MAE) | ☐ | close-to-close only, at 5/20/60 trading days (`quant/evaluate.py:49-65`) |
| **Per-actor + calibrated Evaluation** | ☐ | engine-only, directional hit-rate (`quant/evaluate.py`); no human join, no calibration |
| **Point-in-time data** | ☐ | see Data Model limitations below |
| **Provenance** | ✅ | rows stamped `git_sha`, `config_hash`, `bar_date`; `_runs/<bar_date>.json` config sidecar (`quant/observations.py`) |

## Current limitations — non-point-in-time data

Until each is closed, results carry the bias, replay **must declare it**, and **no decider may rise
above `shadow`** on the resulting record (per `BACKTEST_ENGINE` → `14`'s authority ladder).

| Limitation | Where | Effect |
|-----------|-------|--------|
| **Survivorship / hindsight universe** *(biggest)* | `quant/backtest.py:19-24` | traded set = today's watchlist + current holdings, chosen knowing who survived — optimistic, not repeatable |
| **No price vintage** | `daily_review.py:26-31` (`force_refresh`) | only config is snapshotted; re-running an old session recomputes against *today's* adjusted prices |
| **Un-historized fundamentals** | `quant/observations.py:51,236-239` | `pe`, `analyst_target`, etc. are current snapshots — unsafe for any ≤ t judgment (backtest avoids them today; keep it so until historized) |
| **No slippage** | `quant/backtest.py:95-137` | transaction costs modeled, slippage not — fills at the raw next-open print |

---

# Data Model

Current storage: `data/daily_observations/<profile>/<bar_date>.parquet` — one **wide row per symbol
per session** (~110 columns), written by `quant/observations.py` + `daily_review.py`.

## Against the `DATA_MODEL` contract

| Contract clause | State | Where / note |
|-----------------|-------|--------------|
| **Seven record types, never merged** | ☐ | one wide row **conflates** Fact (OHLC / indicators), Assessment (`state`, valuation), and the Decision label (`intent`, `reason`) — the P1 separation is not persisted |
| **Append-only** | ◐ | files are **last-run-wins** per `bar_date` (`quant/observations.py:435-452`) — a rerun **overwrites**, it does not append a new record |
| **Bitemporal** (`event_at` + `known_at`) | ☐ | rows carry `bar_date` (event) + `create_time` (run), but no **`known_at`** as-of key — this is the root of the price-vintage gap above |
| **As-of reconstructable** | ◐ | reconstructable by `bar_date`, but against *today's* revised prices, not the vintage known then |
| **Separation preserved** | ☐ | denormalized wide row |
| **Provenance-complete** | ✅ | `git_sha`, `config_hash`, `_runs/<bar_date>.json` config sidecar (`quant/observations.py:340-358`) |

## Biggest gap

The store is a **denormalized, event-time-only, overwrite-on-rerun** panel — convenient for analysis,
but it satisfies neither the *separation*, the *append-only*, nor the *bitemporal* clauses. Migrating
to **per-concept append-only records with a `known_at` key** is the work owed — and it is the same
change that closes `BACKTEST_ENGINE`'s price-vintage limitation.

---

# Data Pipeline

Current pipeline: a single top-to-bottom `run()` (`quant/pipeline.py:106`) — load YAML → fetch sources →
`scoring.build_signal` per symbol → assemble the frozen `AnalysisContext`.

## Against the `DATA_PIPELINE` contract

| Contract clause | State | Where / note |
|-----------------|-------|--------------|
| **`known_at` born at the door** | ☐ | no ingestion-time exists — only `bar_date` (event) + run `create_time` (`quant/observations.py:41-42`). A price bar carries only its own `date`; the fetch instant is never recorded per datum |
| **Ingestion separate from interpretation** | ☐ | `scoring.build_signal` (`quant/scoring.py:95`) fuses raw `price` with derived `state`/scores into one `Signal` — there is no standalone Fact layer |
| **Revision = new record (no overwrite)** | ☐ | `cache.write_cache` **unlinks prior files** before writing (`quant/cache.py:44-53`); macro/fundamentals JSON caches replace in place; the day's observation file is overwritten on rerun. No vintage survives a refresh |
| **Separation created at source** | ☐ | raw OHLCV + interpreted `state`/`macd_hist` are written to the *same* parquet row (`quant/observations.py`) |
| **Provenance at ingestion** | ◐ | no source/fetch provenance for price data; `git_sha`/`config_hash` are added only at the observations-write stage; `Fundamentals.as_of` (`quant/models.py:130`) is the sole per-datum fetch stamp |
| **Interpretation via the as-of gateway** | ◐ | in replay, `build_signal` reads a `≤ t` *bar-date* slice (`quant/backtest.py:60`) — but there is no `known_at` gateway, and live ingestion has no gateway abstraction |

**Note — silent adjustment vintage.** Price history is fetched `auto_adjust=True` (`quant/providers.py`),
so every fetch returns *today's* split/dividend-adjusted series — a silent revision of the past, the
same root as the price-vintage limitation above.

## Biggest gap

The pipeline creates exactly what `DATA_MODEL` cannot yet store: a **fused Fact+Assessment with no
`known_at`, overwritten on refresh.** The two gaps are one — closing them means a **Fact-ingestion
stage that stamps `known_at` and never overwrites**, separate from a re-runnable **interpretation
stage**. Same rebuild as Data Model, seen from the ingestion side.

---

# Agents

There is **no first-class agent layer** yet. Three kinds of producer exist, none of them attributed,
append-only records:

- **Lenses** (`quant/` lens modules, aliased `_lens` in `quant/pipeline.py`) are report-only
  **assessors** — macro / sentiment / news / positioning / valuation / levels interpretations that do
  **not** influence Decisions and are **not** stored as separate attributed Assessments (fused into the
  wide observation row).
- **Skills** (`.claude/skills/*` — daily-review, pretrade, macro-review, news-review, sentiment-review,
  weekly-review) are human-invoked **gatherer + assessor** agents that web-search to confirm/refute —
  but their output is **prose in a chat**, never a stored Memory record.
- **The engine** (`quant/decision.py`) is the **decider** (`actor = engine`), but it consumes the fused
  `build_signal` output (raw + interpreted together) — so the decider is **not** isolated from its
  evidence.

## Against the `AGENT_ARCHITECTURE` contract

| Contract clause | State | Where / note |
|-----------------|-------|--------------|
| **Roles named / separated** | ☐ | lenses (assessor) + engine (decider) share the fused pipeline; no explicit roles |
| **Decider isolated from its evidence** | ☐ | `quant/decision.py` decides *from* `build_signal` (raw + interpretation fused) — evidence and choice share one code path |
| **Every output attributed (agent + version)** | ◐ | run-level `git_sha` / `config_hash` only; no per-Assessment assessor + version |
| **Agents earn authority (the ladder)** | ◐ | the lens lifecycle `off→report→shadow→live` is the seed of assessor-reliability; no decider authority ladder exists |
| **Firewall (as-of gateway)** | ◐ | replay slices `≤ t` by bar-date; live skills hit the live web freely (fine live, but no gateway abstraction, no `known_at`) |
| **Append-only, attributed outputs** | ☐ | skill outputs are prose, not records; lens outputs are overwritten in the wide row |

## Biggest gap

Agents today are either **report-only lenses** (assessments that neither influence nor persist as
records) or **chat-only skills** (research that never becomes Memory). Making agents first-class means:
give each producer a **role**, persist every output as an **attributed, append-only** Assessment /
Decision, and **isolate the decider** from the evidence it consumes. The last is a second structural
rebuild (alongside the `known_at` axis): splitting assessment out of `decision.py`'s path.

---

# Reviews

- **`weekly_review.py`** is the closest to a true view — per the refactor it became "a pure view over
  daily capsules" (period deltas, `_1w` features, no second engine run) — but it still originates some
  intents / priorities rather than displaying stored Assessments.
- **`daily_review.py`** is **not a view**: it runs the pipeline (`force_refresh=True`, breadth=full) and
  **writes** the observations panel, then emits **outliers** (RVOL z-score, state flips, RSI extremes).
  It conflates *producing* (that is `DATA_PIPELINE`) with *reviewing*, and it **originates** the outlier
  judgments in-line.
- **Review skills** (`.claude/skills/*` — daily-review, weekly-review, macro-review, news-review,
  sentiment-review) originate judgment as **prose** (catalyst / abnormal / priority) — un-stored,
  un-attributed judgment living in the review.

## Against the `REVIEW_SYSTEM` contract

| Contract clause | State | Where / note |
|-----------------|-------|--------------|
| **Read-only** (produces/stores nothing) | ☐ | `daily_review.py` writes the observations panel — a producer, not a view |
| **Window-parameterized** (one view) | ◐ | daily + weekly are separate scripts; monthly absent; weekly is view-ish |
| **Vantage / as-of honest** | ☐ | reviews read *today's* data; no `known_at` vantage (same root as the Data Model gap) |
| **Arrange, never judge** | ☐ | `daily_review.py` and the skills originate outlier / catalyst / priority judgments in-line |
| **Reproducible** | ◐ | deterministic given inputs — but inputs are today's overwritten data, not a vintage |
| **No Decision** | ✅ | reviews present; the human decides |

## Biggest gap

"Review" today is where a lot of **un-attributed judgment — and even record production — happens.**
Making reviews pure is a three-way decomposition: (1) move the outlier / catalyst / priority judgments
into the **assessor** role as stored Assessments; (2) split `daily_review`'s **pipeline-run + panel-
write** out (that is `DATA_PIPELINE`, not a review); (3) add the **`known_at` vantage** so a historical
review reads honestly. Only the "show me the window" remainder is actually a review — a good sign the
model is coherent, but not a small change.

---

## Raw-material map

| File | Role today | Work owed |
|------|-----------|-----------|
| `quant/backtest.py` | point-in-time, next-open replay reusing the live path | one as-of gateway + conformance test; slippage; close survivorship |
| `quant/evaluate.py` + `evaluate.py` | engine-only forward-return scorecard | → per-actor, path-aware, calibrated (`14`) |
| `quant/observations.py` + `daily_review.py` | append-only-*ish*, provenance-stamped wide panel | per-concept records; `known_at` (bitemporal); stop overwriting on rerun |
| `quant/pipeline.py` + `quant/providers.py` + `quant/cache.py` | fused fetch→signal pipeline; overwrite-on-refresh cache (yfinance / FRED / AV) | split ingestion (stamp `known_at`, append-only) from interpretation; stop unlinking prior vintages |
| `quant/decision.py` + lens modules + `.claude/skills/*` | decider (fused with evidence) · report-only assessors · chat-only research skills | give each a role; persist attributed append-only outputs; isolate the decider from its evidence |
| `daily_review.py` + `weekly_review.py` | daily = producer+review conflated; weekly = view-ish | split producing from reviewing; route flags to assessors; add `known_at` vantage |
