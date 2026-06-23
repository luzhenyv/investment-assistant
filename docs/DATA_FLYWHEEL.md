# Data Flywheel — roadmap

> **Honest framing.** Today this is a *decision engine*, not a prediction engine. The point of the
> flywheel is to earn the right to call it predictive: capture every decision + its factors, grade it
> against what actually happened, and only trust an "edge" once it survives out-of-sample. Nothing
> here promises P&L until evaluation proves it.

The compounding asset is the **labelled panel** at `data/daily_observations/<profile>/<date>.parquet`
— one row per portfolio/watchlist symbol per trading day, with the full feature vector *and* the
system's decision. Load it all with:

```python
import polars as pl
panel = pl.read_parquet("data/daily_observations/<profile>/*.parquet")
```

---

## The flywheel

```
        ┌──────────────────────────────────────────────────────────┐
        │                                                          │
        ▼                                                          │
   1. CAPTURE ──► 2. LABEL ──► 3. EVALUATE ──► 4. OPTIMIZE ──► 5. PREDICT
   decision +     join future   decision-       tune rules,     meta-model
   factors +      returns =     quality         indicators,     sizes/filters
   provenance     the outcome   scorecard       hyperparams     the intents
        │                                                          │
        └──────────── better decisions → richer labels ───────────┘
                                   │
                                   ▼
                            6. MONETIZE (gated on proof)
```

**Core insight:** the wheel only turns if data accrues **daily**, and capture **cannot be
backfilled** — a day not captured is a row lost forever. So Phase 1 (the daily habit) is the whole
game until enough history exists to evaluate.

---

## Phase 0 — Capture  ✅ DONE (this session)

- [x] **Post-close engine** — `daily_review.py` mirrors `weekly_review.py` on a daily cadence; writes
      `output/<profile>/daily_review_*.{md,json}`.
- [x] **Abnormal-volume indicator** — `rvol` + `volume_zscore` (`quant/indicators.py`), `volume_state`
      classifier (`quant/scoring.py`), new `Signal` fields, `volume:` config block.
- [x] **Comprehensive store (54 cols)** — full signals/scores/levels/valuation/role/decision for every
      portfolio + watchlist name; full-universe option positioning; explicit `SCHEMA` dtypes in
      `quant/observations.py`.
- [x] **Decision provenance (76 cols)** — the factors that *gate* the decision (`current_weight`,
      `target_weight`, `ceiling`, `pullback`, `breakout`), position composition, book/market context,
      fundamentals fill-out, plus `git_sha` + `config_hash`.
- [x] **Reproducibility sidecar** — `record_run_meta()` snapshots the resolved config to
      `data/daily_observations/<profile>/_runs/<date>.json` (invisible to the `*.parquet` glob).
- [x] **Explain-the-outliers skill** — `.claude/skills/daily-review/SKILL.md`.

Every stored row is now a self-contained, reproducible supervised-learning feature vector: given the
row + the config snapshot, the decision can be re-derived (and re-optimized).

---

## Phase 1 — Keep it spinning  ⟳ (the daily habit — START NOW)

> This is the gating step. Without daily rows there is nothing to evaluate, optimize, or sell.

- [ ] Run `uv run daily_review.py` **after every US close**, for each profile you care about
      (`PROFILE=demo`, `PROFILE=stocks`, …).
- [ ] Run `uv run python scripts/snapshot_options.py` daily too (option-chain OI/IV history — also
      un-backfillable).
- [ ] **Automate** the two runs ~30 min after the close (16:30 ET) via `cron`/`launchd`, or a
      scheduled reminder. One small wrapper script that loops the profiles.
- [ ] **Data-quality guard:** only run once the daily bar is *final*. Tell-tale of a partial/mid-session
      bar: the whole book shows `rvol < 1` and negative `vol_z` (seen 2026-06-24). Consider a freshness
      assert before `observations.record(...)`.
- [ ] **Back up the store** — periodically commit / copy `data/daily_observations/` (it is the asset).
- [ ] **Scoreboard check** — track `# days captured` and `# decisions logged` so progress is visible.

---

## Phase 2 — Label & Evaluate  (unlock at ~10–20 trading days)

The deferred grader. Turns stored decisions into a measurable quality signal.

- [ ] **`evaluate.py`** — for each stored `(as_of_date, symbol, intent, state)`, join the realized
      forward return at +5 / +20 / +60 trading days. Reuse the price cache `data/cache/*.parquet`
      with `quant/backtest.py::_price_as_of` and `quant/indicators.py::trailing_return`.
- [ ] **Outcome columns (the `y`)** — `fwd_return_5d/20d/60d`, plus a per-intent **hit/miss** under a
      transparent rule: buy intents (`Add Core`/`Increase Exposure`) → forward return > threshold;
      `Close`/`Trim` → avoided drawdown; `Hold` → stayed within band.
- [ ] **Scorecard report** (mirror `quant/report.py` → `output/<profile>/eval_*.{md,json}`) — hit-rate
      and mean forward return **by intent × state × regime**, vs the base rate. Where is the engine
      adding value, where is it noise?
- [ ] Write graded outcomes to their own parquet so they accumulate alongside the panel.

---

## Phase 3 — Optimize  (close the loop)

- [ ] **Hyperparameter sensitivity** — the `config_hash`/sidecar lets you A/B: replay historical
      decisions under alternative thresholds and compare *decision quality* (Phase 2 scorecard), not
      just backtest equity.
- [ ] **Indicator pruning/addition** — keep what the scorecard shows is predictive; drop dead weight.
- [ ] **Feed wins back** into `config/demo/config.yaml` (and private profiles); the `config_hash`
      timeline records what changed and when.

---

## Phase 4 — Predict  (decision engine → prediction engine)

- [ ] Once enough labelled rows exist, train a **meta-model**: features `X` = the 76-col vector,
      target `y` = P(decision correct) or forward-return sign/magnitude. This is meta-labeling.
- [ ] Use the model to **size/filter** the rule engine's intents (a confidence overlay) — *not* to
      replace the transparent rules.
- [ ] **Walk-forward validation**; guard hard against look-ahead and data-snooping — run the
      `backtest-review` skill (Ernest Chan, Ch. 3) on every claimed edge.

---

## Phase 5 — Monetize  (eventual, gated)

- [ ] Only after an edge survives **out-of-sample** validation. The asset is either the calibrated
      edge (better risk-adjusted returns on your own book) **or** the labelled dataset itself.
- [ ] Honest-framing gate: do not market or scale anything the evaluation hasn't earned.

---

## Scoreboard & principles

**Watch:** days captured · decisions logged · hit-rate by intent · mean forward return vs base rate ·
(once a model exists) calibration / Brier score.

**Principles:**
- **Honest framing** — decision engine until evaluation proves predictive edge (matches `README.md`).
- **No look-ahead / no data-snooping** — lean on the `backtest-review` skill.
- **Provenance discipline** — every row already carries `git_sha` + `config_hash`; keep it that way so
  results stay reproducible.

_Direction context for future sessions: see the `daily-review-feature-store` memory and
[ARCHITECTURE.md](ARCHITECTURE.md) / [STRATEGY_ENGINE.md](STRATEGY_ENGINE.md)._
