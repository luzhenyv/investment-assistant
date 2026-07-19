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
| **Bitemporal** (event + knowledge time) | ☐ | rows carry `bar_date` (event) + `create_time` (run), but no **knowledge-time** as-of key — this is the root of the price-vintage gap above |
| **As-of reconstructable** | ◐ | reconstructable by `bar_date`, but against *today's* revised prices, not the vintage known then |
| **Separation preserved** | ☐ | denormalized wide row |
| **Provenance-complete** | ✅ | `git_sha`, `config_hash`, `_runs/<bar_date>.json` config sidecar (`quant/observations.py:340-358`) |

## Biggest gap

The store is a **denormalized, event-time-only, overwrite-on-rerun** panel — convenient for analysis,
but it satisfies neither the *separation*, the *append-only*, nor the *bitemporal* clauses. Migrating
to **per-concept append-only records with a knowledge-time key** is the work owed — and it is the same
change that closes `BACKTEST_ENGINE`'s price-vintage limitation.

---

## Raw-material map

| File | Role today | Work owed |
|------|-----------|-----------|
| `quant/backtest.py` | point-in-time, next-open replay reusing the live path | one as-of gateway + conformance test; slippage; close survivorship |
| `quant/evaluate.py` + `evaluate.py` | engine-only forward-return scorecard | → per-actor, path-aware, calibrated (`14`) |
| `quant/observations.py` + `daily_review.py` | append-only-*ish*, provenance-stamped wide panel | per-concept records; knowledge-time (bitemporal); stop overwriting on rerun |
