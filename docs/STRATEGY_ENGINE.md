# Investment Decision / Strategy Engine

Every rule and number the engine uses to turn market data into a weekly action list. For *where the code lives and how the pieces connect*, see **[ARCHITECTURE.md](ARCHITECTURE.md)**. All values below are from `config/demo/config.yaml` and are verified against the source in `quant/`.

---

## 1. Mental model

The engine codifies one idea: **the asset's state decides which strategy applies.** Each name is classified into a single discrete state every week, and that state routes it to exactly one playbook — so momentum (add to strength) and mean-reversion (buy the dip) coexist without ever firing on the same stock the same week.

It operates at two levels:

- **Portfolio level** — a market *regime* (Panic → Strong Bull) sets the risk posture: protect core in weakness, pyramid winners in strength.
- **Asset level** — per-symbol *state* + portfolio *weight vs target* produce an *intent*.

Scope is **shares only.** Options are surfaced as hints in the report (you pick strikes); they are no-ops in the backtest. This is a decision engine, not a predictor.

The flow each week: **build a `Signal` per symbol → detect the market regime → run the decision ladder per holding → scan the watchlist (or rotate if cash is low) → attach option hints.**

---

## 2. Signal construction (`quant/scoring.py`)

`build_signal(symbol, df, cfg)` reads the latest row of a Polars OHLC frame and assembles a `Signal`. The raw indicators (`quant/indicators.py`): `MA20`, `MA50`, `MA200`, `RSI(14)`, `ATR(14)`, 52-week high/low (252-bar), and **RS** = trailing return over `rs_lookback` (126 bars ≈ 6 months).

**Trend score** — 25 points per bullish stack condition, 0–100:

| Condition | Points |
|---|---|
| `price > MA20` | +25 |
| `MA20 > MA50` | +25 |
| `MA50 > MA200` | +25 |
| `price > MA200` | +25 |

**Momentum score** — bucketed from RSI: `RSI > 70 → 80`, `> 50 → 60`, `> 40 → 40`, else `20`.

**Boolean flags:**
- **Pullback** = `MA50 ≤ price ≤ MA50 + pullback_atr_mult·ATR` (an uptrend dip toward MA50; `pullback_atr_mult = 0.5`).
- **Breakout** = `price ≥ 52-week high`.

**Asset-state ladder** (`asset_state`, first match wins) — uses `accel_rsi = 62`:

| Order | State | Condition | Playbook it routes to |
|---|---|---|---|
| 1 | **Broken** | `price < MA200` or `trend ≤ 25` | Exit the position (Close) |
| 2 | **Mean Reversion** | `pullback` is true | Buy the dip toward target |
| 3 | **Trend Acceleration** | `trend ≥ 75` and (`breakout` or `RSI ≥ 62`) | Pyramid — add to strength, raised ceiling |
| 4 | **Trend Mature** | `trend ≥ 75` | Hold; normal add/trim rules |
| 5 | **Range** | otherwise (above MA200 but weak trend) | Light/no exposure |

Because the ladder is first-match, a name is in exactly one state per week, which is what lets the momentum and mean-reversion rules live side by side.

---

## 3. Market regime (`quant/market.py`)

`detect_market(spy, qqq, vix)` blends index trend with volatility:

```
bull_score = clamp( avg(SPY.trend_score, QQQ.trend_score) + vix_adjustment , 0, 100 )
```

**VIX adjustment:** `< 15 → +10` (calm), `< 20 → 0`, `< 30 → −10` (elevated), `≥ 30 → −25` (fear).

**Regime bands** (from `bull_score`):

| Regime | Band | Posture |
|---|---|---|
| **Panic** | `< 20` | No new buys; only accumulate quality that holds above MA200 |
| **Correction** | `< 40` | Protect core (Hedge); no new entries |
| **Neutral** | `< 60` | Normal rules |
| **Bull** | `< 80` | Normal rules; income overlays allowed |
| **Strong Bull** | `≥ 80` | Maximum conviction |

The decision engine groups these into `WEAK_REGIMES = {Correction, Panic}` (protect core, no watchlist entries) and `CALM_REGIMES = {Bull, Neutral}` (income overlays permitted).

---

## 4. Holding decision ladder (`decision.decide_holding`)

For each held name the engine applies a **7-rule, first-match-wins ladder**. Inputs: the `Signal`, the `Holding`, the `MarketState`, current vs target weight, total value, and whether cash is `low`. `drift_band = 0.20`, `rsi_overbought = 70`.

| # | Rule | Condition | Intent | Notes |
|---|---|---|---|---|
| 0 | **Exit broken** | `state == Broken` and `shares > 0` | **Close** | Sits above Hedge so a broken name leaves rather than being defended. `dollar_gap = −full position` |
| 1 | **Protect core** | regime in `{Correction, Panic}` and `core > 0` | **Hedge** | Defend, don't sell core |
| 2 | **Panic accumulation** | `regime == Panic` and `price > MA200` and not cash-low | **Add Core** | Buy quality that holds the trend, one step |
| 3 | **Pyramid** | `state == Trend Acceleration` and `current < ceiling` and not cash-low | **Add Core** | Add to strength toward the *raised* ceiling, one step |
| 4 | **Trim overweight** | `current > ceiling` | **Trim** | Accelerating names use a raised ceiling, so winners aren't trimmed merely for exceeding base target |
| 5 | **Buy the dip** | `current < target·(1−drift)` and `pullback` and not cash-low and `regime ≠ Panic` | **Add Core** | Underweight + healthy pullback to MA50, one step |
| 6 | **Generate income** | `current ≥ target` and `RSI > 70` and regime in `{Bull, Neutral}` | **Generate Income** | Extended at target → sell premium (heuristic; no IV data in v0.1) |
| 7 | **Default** | — | **Hold** | No rule triggered |

The ordering matters: an accelerating winner is checked for *adding* (rule 3) before *trimming* (rule 4); a Panic regime accumulates (rule 2) before the normal dip-buy (rule 5).

---

## 5. Position sizing & target weights

**Target weight** (`effective_target`): a hand-set entry in `config.yaml: target_weights`, else the default `lifecycle.entry_default_weight = 0.06`. A target is a **ceiling, not a floor** — a name can sit below target if the add conditions never trigger.

**Three conviction tiers** (let bigger / stronger-fundamental names size larger):

| Tier | Target | Scale-in step (`target/3`) | Accel ceiling (`target × 4/3`) | Demo names |
|---|---|---|---|---|
| Mega-cap | **0.15** | 5.0% | 20.0% | NVDA, GOOG, MSFT, META, AMZN, AVGO |
| Mid/large growth | **0.10** | 3.3% | 13.3% | AMD, MU, MRVL, TSM, PLTR, HOOD |
| Small high-growth | **0.06** | 2.0% | 8.0% | CRWD, NET, HIMS, RKLB, NBIS (and any unlisted name) |

**Ceiling** (`effective_ceiling`) — the upper band before Trim fires. Only the *upper* band is state-aware; the lower (Add) band stays `target·(1−drift)` so dips are bought at the same level:

```
base ceiling                 = target · (1 + drift_band)            # = target × 1.20
Trend Acceleration ceiling   = target · (1 + accel_extra_steps / max_steps)   # = target × 4/3
```

With `accel_extra_steps = 1` and `max_steps = 3`, an accelerating winner gets **one extra scale-in step** above target (15%→20%, 10%→13.3%, 6%→8%). A legacy `accel_mult` band (`target·(1+drift)·accel_mult`) is the fallback when `accel_extra_steps` is not configured — some private profiles may still use it.

**Staged scale-in** (`staged_gap`) — every buy adds at most `target / max_steps` of weight (one "step"), capped by the room remaining up to the ceiling. So a position builds over a few weekly adds instead of filling in one shot, reducing timing luck.

---

## 6. Watchlist entry & rotation (`scan_watchlist`, `rotation`)

These add *new* names. The engine holds at most `max_positions = 7` of the wider watchlist.

**Entry — `scan_watchlist`** (used when cash is **not** low):
- Skipped entirely in weak regimes (`{Correction, Panic}`).
- Candidates = unheld names whose `state ∈ {Trend Acceleration, Trend Mature, Mean Reversion}` and `trend_score ≥ entry_trend_min (75)`.
- Ranked by **RS** (strongest first); fill up to `open_slots = max_positions − held`.
- Each entry is intent **Increase Exposure**, sized as the first scale-in step toward its target.

**Rotation — `rotation`** (used only when cash is **low**, i.e. at the floor):
- Find the strongest fresh candidate (by RS) and the weakest held **laggard** — but **never** a Trend Acceleration winner.
- Require an edge: candidate RS must beat laggard RS by more than `rotation_margin = 0.10`; otherwise do nothing.
- Graduated exit: if the laggard is `Range`/`Broken` or has negative RS → **Close** it; else **Trim** it one step.
- Returns `[exit_action, entry]` so the exit frees cash before the entry spends it. At most one rotation per week.

---

## 7. Cash management

`cash_band` governs deployment, measured as `cash / total_value`:

- **`min: 0.10`** — below this, cash is `low`: all new buys are suppressed and only `rotation` may free capital. (Add/Income rules carry a `not cash_low` guard.)
- **`max: 0.25`** — above this, the weekly report flags how much is deployable.

`weekly_review.py` also prints a **config reminder**: any held or buy-candidate name with no explicit `target_weights` entry (riding the 0.06 default) is listed, so you can size it intentionally.

---

## 8. Intent → options strategy hints

`attach_strategy_hints` maps each intent to suggested structures via `config.yaml:intent_strategy_map`. **Hints only** — the engine picks no strikes or expiries, and the backtester ignores the option legs.

| Intent | Suggested structures |
|---|---|
| Add Core | Buy shares, Cash Secured Put |
| Increase Exposure | Bull Call Spread |
| Trim | Sell shares, Covered Call |
| Generate Income | Covered Call, Cash Secured Put |
| Hedge | Bear Put Spread |
| Close | Sell shares |
| Hold | — |

---

## 9. How the backtest replays it (`quant/backtest.py`)

The backtester reuses the **same** scoring / market / decision functions as the live run — it just feeds them as-of-date slices.

- **Cadence:** skip the first `WARMUP = 200` trading days (MA200 window), then rebalance every `STEP = 5` trading days (≈ weekly), filtered to `backtest.start = 2019-01-01`.
- **No look-ahead:** each frame is sliced to `date ≤ T`; indicators read the latest (as-of-*T*) value.
- **Execution (`_execute`)** maps intents coarsely to trades at *T*'s close:
  - `Add Core` / `Increase Exposure` → buy toward target (honoring the rec's `dollar_gap` so acceleration pyramids past base target), never spending below the cash floor.
  - `Trim` → sell down (one step in rotation, else to target). `Close` → sell to zero.
  - `Hedge` / `Generate Income` / `Hold` → **no equity effect** (options overlays not modeled).
- **Costs:** `per_trade_bps = 5` on every buy/sell; idle cash accrues `cash_apy = 0.04` between rebalances.
- **Metrics (`_summarize`):** total return, CAGR, annualized Sharpe (excess of cash yield, 52 periods/yr), max drawdown + longest underwater run, total costs, and SPY buy-hold for comparison.
- **Out-of-sample split:** `train_end = 2023-01-01` splits the curve into `in_sample` vs `out_of_sample` segments, reported separately so you can see overfitting.

---

## 10. Validated results & honest caveats

A representative replay on the demo universe (2019-01 → 2026-06, ~7.4 yr through COVID and 2022): roughly **CAGR ~40%, Sharpe ~1.5, max drawdown ~22%** versus SPY at a much deeper drawdown. The ~22% max drawdown corresponds to the COVID crash window — evidence the Close/Hedge rules cushion a real crash, landing within the target ~25% drawdown tolerance.

**Read the shape, not the magnitude.** The large absolute return is **selection bias**: the universe is a hand-picked set of AI-supercycle winners, not a point-in-time index, and several names (NBIS, HOOD, HIMS, RKLB) have little or no in-sample history, so their tier sizing is essentially untested by the backtest. The trustworthy signal is the *risk-adjusted profile* (Sharpe ≈ 1.5, drawdown within tolerance), not the headline CAGR. Treat the backtest as a sanity check on the rules, not a P&L promise.

---

## 11. Upgrade levers & open questions

**Tuning knobs (all in `config.yaml`, no code change):**

| Section | Levers |
|---|---|
| `scoring` | `rsi_overbought`, `pullback_atr_mult`, `accel_rsi`, `rs_lookback` |
| `drift_band`, `cash_band` | rebalance tolerance; cash floor/ceiling |
| `lifecycle` | `max_positions`, `entry_trend_min`, `entry_default_weight`, `max_steps`, `accel_extra_steps`, `rotation_margin` |
| `target_weights` | per-name conviction tiers |
| `backtest` | `start`, `train_end`, `costs` |

**Structural extension points (need code):**
- New asset states or a refined state ladder (`scoring.asset_state`).
- Score-derived weights instead of hand-set `target_weights` (a deliberately rejected direction so far — current policy is *state-aware ceilings* on hand-set targets).
- Real options modeling in the backtest (today Hedge / Generate Income are no-ops).
- A point-in-time, survivorship-free universe to remove the selection bias in §10.
- Additional regime inputs beyond SPY/QQQ trend + VIX (breadth, credit, rates).

**Validation discipline (carry into every change):**
- Gate every rule change on the backtester **vs SPY/QQQ** — whipsaw is the main failure mode.
- Watch the out-of-sample segment, not just the headline.
- Clear `data/cache/*.parquet` when you change `data.period` (the cache reuses today's file regardless of the requested range).
