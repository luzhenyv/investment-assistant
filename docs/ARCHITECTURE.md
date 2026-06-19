# Software Architecture

How the `investment-assistant` codebase is built: the modules, how data flows through them, the
config/profile system, and where to plug in changes. For *what the rules actually decide* (scoring,
regime, the decision ladder, sizing), see **[STRATEGY_ENGINE.md](STRATEGY_ENGINE.md)**. For
operational setup of a real account, see **[REAL_PORTFOLIO_SETUP.md](REAL_PORTFOLIO_SETUP.md)** and
the top-level **[README.md](../README.md)**.

---

## 1. Purpose & design philosophy

This is a **decision engine, not a prediction engine.** It does not forecast prices. Once a week it
reads your portfolio + market data and prints an action list answering one question: *"What should I
do next week?"* Its value is **discipline** — the same rules applied unemotionally every week.

Three architectural principles fall out of that:

- **Pure-function core.** Everything from indicators through the decision rules is a pure function:
  inputs in, value out, no global state, no hidden I/O. Config is passed in as a plain `dict`. This
  makes every decision reproducible and trivially testable.
- **Single network boundary.** Only `quant/providers.py` touches the network (yfinance). Everything
  downstream is deterministic given the fetched frames.
- **Latest-value (as-of) semantics.** Indicators read the *last row* of a price frame. The live run
  passes the full history (latest = today); the backtester slices the frame to week *T* (latest =
  as-of *T*). The **same code** therefore serves both live and historical replay with no look-ahead.

> **Honest framing.** The thresholds in `config/demo/config.yaml` are *codified judgment*, not
> statistically validated edges. `backtest.py` is an approximate equity simulation (intents map
> coarsely to trades; options overlays are no-ops), a sanity check on the rules — not a P&L promise.

---

## 2. System map

```
                  config.yaml ─┐
   portfolio.yaml ─────────────┤  (selected by PROFILE via quant/profiles.py)
   watchlist.yaml ─────────────┘
                                │
                                ▼
            ┌──────────────────────────────────┐
   network  │ providers.py  ──►  cache.py       │   yfinance ─► pandas ─► Polars
   boundary │ (yfinance)        (Parquet, data/cache/)                 + daily-freshness cache
            └──────────────────────────────────┘
                                │  {symbol: OHLC Polars frame}, VIX
                                ▼
          indicators.py ──► scoring.py ──► Signal (per symbol)
                                │
                                ├──► market.py ──► MarketState  (regime from SPY/QQQ/VIX)
                                ▼
          portfolio.py (value, weights, cash status)
                                │
                                ▼
          decision.py  ──► Recommendation[]  (intent per holding + watchlist scan/rotation)
                                │
                ┌───────────────┴────────────────┐
                ▼                                 ▼
        report.py                          backtest.py
   (weekly: .md + .json)         (replay loop → BacktestResult)
                                                  │
                                                  ▼
                                          plotting.py (.html equity figure)
```

Two entry points sit on top of this pipeline:

- **`weekly_review.py`** — runs the pipeline **once** on the latest data and writes a report.
- **`backtest.py`** — runs the *score → detect → decide* portion in a **weekly loop over history**
  and simulates trades to produce an equity curve.

---

## 3. Module-by-module reference

All live under `quant/`. Each module is small and single-purpose.

| Module | Responsibility | Key public surface |
|---|---|---|
| `models.py` | Plain dataclasses passed between layers; no logic, no I/O | `MarketState`, `Signal`, `Holding`, `Recommendation` |
| `indicators.py` | Pure technical indicators over a Polars price column | `moving_average`, `rsi`, `atr`, `trailing_return`, `high_52w`, `low_52w` |
| `scoring.py` | Turn indicators into 0–100 scores, flags, and an asset state | `build_signal`, `trend_score`, `momentum_score`, `is_pullback`, `is_breakout`, `asset_state` |
| `market.py` | Derive market regime from index trends + VIX | `detect_market`, `_vix_adjustment`, `_regime` |
| `decision.py` | The rule engine: regime + scores + weights → intent | `decide_holding`, `scan_watchlist`, `rotation`, `effective_target`, `effective_ceiling`, `staged_gap`, `attach_strategy_hints` |
| `portfolio.py` | Load portfolio YAML; compute value, weights, cash status | `load_portfolio`, `portfolio_value`, `current_weights`, `cash_status` |
| `providers.py` | yfinance wrapper; **the only network I/O** | `fetch_history`, `fetch_vix`, `fetch_vix_history` |
| `cache.py` | Parquet cache with daily-freshness + stale fallback | `load_or_fetch`, `write_cache` |
| `profiles.py` | Resolve which account's files to use (`PROFILE` env var) | `resolve(root)` |
| `report.py` | Render the weekly review as Markdown + JSON | `render_markdown`, `generate` |
| `plotting.py` | Render a `BacktestResult` as an interactive Plotly HTML | `write_equity_figure` |
| `backtest.py` | Replay the weekly strategy over history; compute metrics | `run`, `BacktestResult`, `_execute`, `_summarize` |

Notes on the more involved modules:

- **`indicators.py`** — Each function takes a Polars `Series` and returns the *latest* scalar via
  `.tail(window)`. `trailing_return` (relative strength) returns `0.0` when history is shorter than
  `lookback+1`, so young tickers rank low rather than crash. `high_52w`/`low_52w` use a 252-bar tail.
- **`providers.py`** — yfinance returns pandas; this is the one place pandas→Polars conversion
  happens (`_to_polars`). Canonical frame schema: a `date` (Polars `Date`) column + OHLC. `fetch_vix`
  falls back to `20.0` (neutral) when VIX is unavailable.
- **`cache.py`** — One file per symbol, `data/cache/SYMBOL_START_END.parquet`. Policy: (1) reuse
  today's cached file if valid; (2) else download and cache; (3) if the download fails, fall back to
  the newest valid cached file *of any age*. "Valid" = at least `min_rows` rows. Writing a new file
  deletes older files for that symbol to avoid clutter. **Caveat:** the cache keys on "written today",
  not on the requested date range — so when you change `data.period`, clear `data/cache/*.parquet` or
  it will reuse today's file at the old range.

---

## 4. End-to-end data flow

### `weekly_review.py` (live, runs once)

1. `profiles.resolve(ROOT)` → `(config, portfolio, watchlist, out_dir)` for the active `PROFILE`.
2. Load the three YAMLs; `symbols = watchlist ∪ holdings`.
3. `providers.fetch_history(symbols + SPY/QQQ, period, min_rows)` and `providers.fetch_vix(period)`
   (both via the Parquet cache).
4. `scoring.build_signal(sym, df, cfg)` for every symbol → `{sym: Signal}`.
5. `market.detect_market(spy, qqq, vix)` → `MarketState`. (Aborts if SPY/QQQ missing.)
6. `portfolio.portfolio_value` / `current_weights` / `cash_status` → totals, weights, and whether
   cash is `low`.
7. For each holding: `decision.decide_holding(...)` → a `Recommendation`.
8. **Branch on cash:** if cash is `low`, `decision.rotation(...)` (rotate a laggard to fund the best
   candidate); otherwise `decision.scan_watchlist(...)` for up to `max_positions − len(holdings)` new
   names.
9. `decision.attach_strategy_hints(...)` adds the option-structure hints from `intent_strategy_map`.
10. Flag any held / buy-candidate names that have **no `target_weights` entry** (riding the default
    weight) — printed to console and surfaced in the report's "Config reminder".
11. `report.generate(...)` writes `output/<profile>/weekly_report_<timestamp>.{md,json}`.

### `backtest.py` (historical replay, weekly loop)

1–3. Same load + fetch, but pulls **full history** and `providers.fetch_vix_history(period)`.
4. `backtest.run(history, vix_hist, cfg)`:
   - Rebalance dates = SPY trading days `[WARMUP::STEP]` (skip the first `WARMUP=200` days for the
     MA200 window; then every `STEP=5` days ≈ weekly), filtered to `backtest.start`.
   - For each date *T*: slice every frame to as-of *T*, build signals as-of *T*, detect regime,
     accrue cash interest since the previous rebalance, then run the **same** `decide_holding` /
     `rotation` / `scan_watchlist` as live, and `_execute(...)` the resulting intents into share
     changes at *T*'s close (charging `per_trade_bps`).
   - Records equity, SPY price, and composition each week.
5. `_summarize(...)` computes total return, CAGR, Sharpe, max drawdown + duration, total costs, and
   (if `train_end` is set) in-sample vs out-of-sample segments → `BacktestResult`.
6. `backtest.py` writes `output/<profile>/backtest_report.json` and `plotting.write_equity_figure`
   writes `backtest_report.html`.

---

## 5. Config & profile system

`quant/profiles.py` selects which account's files to run against via the `PROFILE` environment
variable, so real holdings never sit next to the shared demo:

| `PROFILE` | Files | Output |
|---|---|---|
| `demo` (default) | `config/demo/{config,portfolio,watchlist}.yaml` | `output/demo/` |
| `stocks` | `private/stocks/{config,portfolio,watchlist}.yaml` | `output/stocks/` |
| `etf` | `private/etf/{config,portfolio,watchlist}.yaml` | `output/etf/` |

`private/` is git-ignored and kept as its own local-only repo, so real positions never reach the
GitHub remote. `resolve()` raises `SystemExit` with a pointer to `REAL_PORTFOLIO_SETUP.md` if any of
the three files is missing.

**The three YAML inputs:**

- **`config.yaml`** — all tunable strategy parameters (data window, backtest params, bands, scoring
  thresholds, lifecycle, target weights, intent→strategy map). Documented field-by-field in
  [STRATEGY_ENGINE.md](STRATEGY_ENGINE.md).
- **`watchlist.yaml`** — `symbols: [ ... ]`, the universe scanned each week for new entries.
- **`portfolio.yaml`** — current positions, hand-updated:
  ```yaml
  cash: 30000
  positions:
    NVDA:
      core: 100      # long-term shares — protected in weak markets (Hedge, not sold)
      trading: 20    # tactical shares (core + trading = total shares)
      avg_cost: 450  # informational; not used by the engine
  ```

`config/demo/` also contains an `options.yaml` and there is a `config/templates/` directory with
`*.example.yaml` starters — neither is read by the v0.1 pipeline.

---

## 6. Key data structures

All four are dataclasses in `quant/models.py`.

- **`MarketState`** — `regime: str` (`Panic | Correction | Neutral | Bull | Strong Bull`),
  `bull_score: float` (0–100), `notes: list[str]`. Produced by `market.detect_market`.
- **`Signal`** — per-symbol snapshot. `symbol, price, ma20, ma50, ma200, rsi, atr, high_52w, low_52w`
  (raw), `trend_score, momentum_score` (0–100), `pullback, breakout` (bool), `state` (asset-state
  label), `rs` (relative strength = trailing return). Produced by `scoring.build_signal`.
- **`Holding`** — `symbol, core, trading, avg_cost`; property `shares = core + trading`. Loaded by
  `portfolio.load_portfolio`.
- **`Recommendation`** — the decision output. `symbol, intent` (`Add Core | Trim | Hold | Generate
  Income | Hedge | Increase Exposure | Close`), `reason`, `scores: dict` (diagnostics),
  `strategy_hint: list[str]` (option structures), `dollar_gap: float | None` (signed $ to reach
  target). Produced by `decision.*`.

`BacktestResult` (in `quant/backtest.py`, not `models.py`) carries the equity-curve time series plus
the summary metrics and the in/out-of-sample `segments` dict.

---

## 7. Dependencies & how to run

`pyproject.toml` (Python ≥ 3.11), run with `uv`:

- **Runtime:** `polars` (dataframes), `pyarrow` (Parquet), `yfinance` (data), `pyyaml` (config),
  `plotly` (charts).
- **Dev:** `pytest`.

```bash
uv sync                              # install dependencies
uv run weekly_review.py              # this week's report (PROFILE=demo by default)
PROFILE=stocks uv run backtest.py    # replay a private profile over history
uv run pytest                        # run the suite
```

Tests live in `tests/` (`test_indicators.py`, `test_scoring.py`, `test_decision.py`,
`test_backtest.py`, `test_cache.py`) and use synthetic frames — no network.

---

## 8. Directory map

```
investment-assistant/
├── weekly_review.py          # entry point: live weekly report
├── backtest.py               # entry point: historical replay
├── quant/                    # the engine (all pure except providers/cache)
│   ├── models.py             # dataclasses
│   ├── indicators.py         # raw technicals
│   ├── scoring.py            # signals + asset state
│   ├── market.py             # regime detection
│   ├── decision.py           # the rule engine
│   ├── portfolio.py          # value / weights / cash status
│   ├── providers.py          # yfinance (only network I/O)
│   ├── cache.py              # Parquet cache
│   ├── profiles.py           # PROFILE resolution
│   ├── report.py             # markdown + json output
│   ├── plotting.py           # plotly equity figure
│   └── backtest.py           # replay loop + metrics
├── config/
│   ├── demo/                 # public demo profile (config/portfolio/watchlist/options)
│   └── templates/            # *.example.yaml starters
├── private/                  # git-ignored real profiles (stocks/, etf/) — own local repo
├── data/cache/               # SYMBOL_START_END.parquet
├── output/{demo,stocks,etf}/ # generated reports + backtest html/json
├── tests/                    # pytest suite (synthetic data)
└── docs/                     # this file, STRATEGY_ENGINE.md, REAL_PORTFOLIO_SETUP.md
```

---

## 9. Extension points & limitations

This is the foundation for upcoming architecture upgrades. The clean seams:

- **Add an indicator** → write a pure function in `indicators.py`, compute it inside
  `scoring.build_signal`, add the field to `Signal` in `models.py`.
- **Change how a symbol is classified** → `scoring.asset_state` (the first-match state ladder) and
  the `trend_score` / `momentum_score` functions.
- **Add or reorder a decision rule** → `decision.decide_holding` is a first-match-wins ladder; insert
  a rule at the right priority. Entry/rotation logic lives in `scan_watchlist` / `rotation`.
- **Change sizing** → `effective_target`, `effective_ceiling`, `staged_gap` in `decision.py`.
- **Add a market input** → `market.detect_market` (currently SPY + QQQ trend + VIX).
- **New output channel** → `report.py` (the JSON payload is already structured for downstream tools).
- **Add a data source** → `providers.py` is the only network boundary; keep new sources behind it and
  convert to the canonical Polars OHLC schema there.

**Current limitations (deliberate for v0.1):**

- **Single data provider** (yfinance, free). No fundamentals, no intraday, no options chains.
- **No broker integration** — `portfolio.yaml` is hand-updated; the engine only *recommends*.
- **Options are hints only** — intents map to suggested structures via `intent_strategy_map`, but the
  engine picks no strikes/expiries and the backtester treats Hedge / Generate Income as no-ops.
- **Survivorship / selection bias** — the traded universe is a hand-picked watchlist, not a
  point-in-time index, so historical results are optimistic (see
  [STRATEGY_ENGINE.md §10](STRATEGY_ENGINE.md)). yfinance has no historical index membership to fix
  this; the `train_end` split is a partial mitigation only.
- **No persisted state between runs** — each run recomputes from data + the YAML files; there is no
  database.
