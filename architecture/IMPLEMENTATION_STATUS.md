# Backtest — Implementation Status v1.0

> **Layer: Architecture (status note).** This tracks where **today's Python implementation** stands
> against the `BACKTEST_ENGINE` contract. Unlike `BACKTEST_ENGINE`, this doc **ages with the code** —
> the file/line references below *will* rot, and that is expected. When the code is rewritten, this doc
> is rewritten; the contract is not. Nothing here is a specification; it is a snapshot.

Legend: ✅ satisfies the contract clause · ◐ partial · ☐ owed.

---

## Against the `BACKTEST_ENGINE` contract

| Contract clause | State | Where / note |
|-----------------|-------|--------------|
| **Single Decision Path** — replay runs the live engine, not a copy | ✅ | replay calls `scoring.build_signal`, `market.detect_market`, `decision.decide_holding / rotation / scan_watchlist` (`quant/backtest.py:191-228`) |
| **As-of gateway** — all judgment reads ≤ t | ◐ | frames sliced to `date ≤ t` (`quant/backtest.py:60-61`, applied `:173,194,197`); indicators trailing-window over the slice (`quant/scoring.py:98-100`). Correct, but **bypassable** — not one enforced gateway |
| **Conformance test** — fails if any judgment reads > t | ☐ | none exists yet |
| **Next-instant execution** | ✅ | fills at next session open (`_open_as_of :69-72`, `t_exec = t+1 :232-240`); final bar dropped (`:233-234`) |
| **Path-aware Outcome** (terminal + MFE/MAE) | ☐ | close-to-close only, at 5/20/60 trading days (`quant/evaluate.py:49-65`) |
| **Per-actor + calibrated Evaluation** | ☐ | engine-only, directional hit-rate (`quant/evaluate.py`); no human join, no calibration |
| **Point-in-time data** | ☐ | see limitations below |
| **Provenance** (supports audit/replay) | ✅ | rows stamped `git_sha`, `config_hash`, `bar_date`; `_runs/<bar_date>.json` config sidecar (`quant/observations.py`) |

---

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

## Raw-material map

| File | Role today | Work owed |
|------|-----------|-----------|
| `quant/backtest.py` | point-in-time, next-open replay reusing the live path | one as-of gateway + conformance test; slippage; close survivorship |
| `quant/evaluate.py` + `evaluate.py` | engine-only forward-return scorecard | → per-actor, path-aware, calibrated (`14`) |
| `quant/observations.py` + `daily_review.py` | append-only, provenance-stamped panel | add a **price-vintage** snapshot, not only config |
